from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from textwrap import dedent
from typing import Any

import numpy as np
import pandas as pd

from .config import StrategyConfig


DEFAULT_FINANCE_MODEL = "ProsusAI/finbert"


@dataclass(frozen=True)
class CsvScoreProvider:
    scores: pd.DataFrame
    max_age_days: int = 30

    @classmethod
    def from_csv(cls, path: str | Path, max_age_days: int = 30) -> "CsvScoreProvider":
        frame = pd.read_csv(path)
        required = {"date", "symbol", "model_score"}
        missing = required - set(frame.columns)
        if missing:
            raise ValueError(f"Score CSV is missing columns: {', '.join(sorted(missing))}")
        frame = frame.copy()
        frame["date"] = pd.to_datetime(frame["date"])
        frame["symbol"] = frame["symbol"].astype(str)
        frame["model_score"] = pd.to_numeric(frame["model_score"], errors="coerce")
        frame = frame.dropna(subset=["date", "symbol", "model_score"])
        return cls(frame.sort_values(["date", "symbol"]), max_age_days=max_age_days)

    def predict_scores(
        self,
        prices: pd.DataFrame,
        config: StrategyConfig,
        asof: pd.Timestamp | None = None,
    ) -> pd.Series:
        if self.scores.empty:
            return pd.Series(dtype=float)
        if asof is None:
            asof = pd.Timestamp(prices.index[-1])
        asof = pd.Timestamp(asof)
        start = asof - pd.Timedelta(days=self.max_age_days)
        rows = self.scores[(self.scores["date"] <= asof) & (self.scores["date"] >= start)]
        if rows.empty:
            return pd.Series(dtype=float)
        latest = rows.sort_values("date").groupby("symbol", as_index=False).tail(1)
        ranked = latest.set_index("symbol")["model_score"].rank(pct=True)
        ranked.name = "model_score"
        return ranked.astype(float)


@dataclass(frozen=True)
class CompositeScoreProvider:
    providers: tuple[Any, ...]

    def predict_scores(
        self,
        prices: pd.DataFrame,
        config: StrategyConfig,
        asof: pd.Timestamp | None = None,
    ) -> pd.Series:
        pieces = []
        for provider in self.providers:
            scores = provider.predict_scores(prices, config, asof)
            if scores is not None and not scores.empty:
                pieces.append(scores.rename(len(pieces)))
        if not pieces:
            return pd.Series(dtype=float)
        frame = pd.concat(pieces, axis=1)
        combined = frame.mean(axis=1).rank(pct=True)
        combined.name = "model_score"
        return combined.astype(float)


def score_texts_with_hf_model(
    input_path: str | Path,
    out_path: str | Path,
    model_id: str = DEFAULT_FINANCE_MODEL,
    adapter_path: str | None = None,
    date_column: str = "date",
    symbol_column: str = "symbol",
    text_column: str = "text",
    batch_size: int = 8,
    device: str | None = None,
) -> pd.DataFrame:
    transformers, torch_module = require_transformers()
    raw = pd.read_csv(input_path)
    missing = {date_column, symbol_column, text_column} - set(raw.columns)
    if missing:
        raise ValueError(f"Input text CSV is missing columns: {', '.join(sorted(missing))}")

    tokenizer = transformers.AutoTokenizer.from_pretrained(model_id)
    model = transformers.AutoModelForSequenceClassification.from_pretrained(model_id)
    if adapter_path:
        peft = require_peft()
        model = peft.PeftModel.from_pretrained(model, adapter_path)

    device_name = choose_text_device(torch_module, device)
    model.to(device_name)
    model.eval()

    rows: list[dict[str, object]] = []
    texts = raw[text_column].fillna("").astype(str).tolist()
    for start in range(0, len(texts), batch_size):
        chunk = texts[start : start + batch_size]
        encoded = tokenizer(chunk, truncation=True, padding=True, return_tensors="pt")
        encoded = {key: value.to(device_name) for key, value in encoded.items()}
        with torch_module.no_grad():
            logits = model(**encoded).logits
            probs = torch_module.softmax(logits, dim=-1).detach().cpu().numpy()
        for offset, probability in enumerate(probs):
            source_row = raw.iloc[start + offset]
            scored = probability_to_score(probability, model.config.id2label)
            rows.append(
                {
                    "date": source_row[date_column],
                    "symbol": str(source_row[symbol_column]),
                    "model_score": scored["model_score"],
                    "positive_probability": scored["positive_probability"],
                    "neutral_probability": scored["neutral_probability"],
                    "negative_probability": scored["negative_probability"],
                    "model_id": model_id,
                    "adapter_path": adapter_path or "",
                }
            )

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(rows)
    frame.to_csv(out, index=False)
    return frame


def probability_to_score(probability: np.ndarray, id2label: dict[int, str]) -> dict[str, float]:
    labels = {int(key): value.lower() for key, value in id2label.items()}
    positive = 0.0
    neutral = 0.0
    negative = 0.0
    for idx, prob in enumerate(probability):
        label = labels.get(idx, str(idx)).lower()
        if "pos" in label or "bull" in label:
            positive += float(prob)
        elif "neg" in label or "bear" in label:
            negative += float(prob)
        elif "neu" in label:
            neutral += float(prob)
    if positive == 0.0 and negative == 0.0 and len(probability) == 2:
        negative = float(probability[0])
        positive = float(probability[1])
    return {
        "model_score": positive - negative,
        "positive_probability": positive,
        "neutral_probability": neutral,
        "negative_probability": negative,
    }


def write_peft_training_script(
    out_path: str | Path,
    base_model: str,
    train_csv: str,
    hub_model_id: str,
    text_column: str = "text",
    label_column: str = "label",
    num_labels: int = 3,
    epochs: int = 3,
    learning_rate: float = 2e-4,
    lora_r: int = 16,
    lora_alpha: int = 32,
    lora_dropout: float = 0.05,
    max_length: int = 256,
) -> Path:
    script = render_peft_training_script(
        base_model=base_model,
        train_csv=train_csv,
        hub_model_id=hub_model_id,
        text_column=text_column,
        label_column=label_column,
        num_labels=num_labels,
        epochs=epochs,
        learning_rate=learning_rate,
        lora_r=lora_r,
        lora_alpha=lora_alpha,
        lora_dropout=lora_dropout,
        max_length=max_length,
    )
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(script, encoding="utf-8")
    return out


def render_peft_training_script(
    base_model: str,
    train_csv: str,
    hub_model_id: str,
    text_column: str,
    label_column: str,
    num_labels: int,
    epochs: int,
    learning_rate: float,
    lora_r: int,
    lora_alpha: int,
    lora_dropout: float,
    max_length: int,
) -> str:
    return dedent(
        f"""\
        # /// script
        # dependencies = [
        #   "accelerate>=1.0",
        #   "datasets>=3.0",
        #   "peft>=0.13",
        #   "torch>=2.2",
        #   "transformers>=4.45",
        # ]
        # ///

        from datasets import load_dataset
        from peft import LoraConfig, TaskType, get_peft_model
        from transformers import AutoModelForSequenceClassification, AutoTokenizer, DataCollatorWithPadding, Trainer, TrainingArguments


        BASE_MODEL = {base_model!r}
        TRAIN_CSV = {train_csv!r}
        HUB_MODEL_ID = {hub_model_id!r}
        TEXT_COLUMN = {text_column!r}
        LABEL_COLUMN = {label_column!r}
        NUM_LABELS = {num_labels}
        MAX_LENGTH = {max_length}


        def main():
            dataset = load_dataset("csv", data_files=TRAIN_CSV)["train"]
            dataset = dataset.class_encode_column(LABEL_COLUMN)
            split = dataset.train_test_split(test_size=0.2, seed=42, stratify_by_column=LABEL_COLUMN)

            tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL)

            def tokenize(batch):
                return tokenizer(batch[TEXT_COLUMN], truncation=True, max_length=MAX_LENGTH)

            tokenized = split.map(tokenize, batched=True)
            tokenized = tokenized.rename_column(LABEL_COLUMN, "labels")

            model = AutoModelForSequenceClassification.from_pretrained(BASE_MODEL, num_labels=NUM_LABELS)
            peft_config = LoraConfig(
                task_type=TaskType.SEQ_CLS,
                r={lora_r},
                lora_alpha={lora_alpha},
                lora_dropout={lora_dropout},
                bias="none",
                modules_to_save=["classifier"],
            )
            model = get_peft_model(model, peft_config)
            model.print_trainable_parameters()

            args = TrainingArguments(
                output_dir="hf_finance_peft",
                learning_rate={learning_rate},
                per_device_train_batch_size=16,
                per_device_eval_batch_size=16,
                num_train_epochs={epochs},
                eval_strategy="epoch",
                save_strategy="epoch",
                load_best_model_at_end=True,
                metric_for_best_model="eval_loss",
                push_to_hub=True,
                hub_model_id=HUB_MODEL_ID,
                report_to="none",
            )
            trainer = Trainer(
                model=model,
                args=args,
                train_dataset=tokenized["train"],
                eval_dataset=tokenized["test"],
                tokenizer=tokenizer,
                data_collator=DataCollatorWithPadding(tokenizer=tokenizer),
            )
            trainer.train()
            trainer.push_to_hub()


        if __name__ == "__main__":
            main()
        """
    )


def require_transformers() -> tuple[Any, Any]:
    try:
        import torch
        import transformers
    except ImportError as exc:
        raise RuntimeError("Install Hugging Face dependencies with `uv pip install -r requirements-hf.txt`.") from exc
    return transformers, torch


def require_peft() -> Any:
    try:
        import peft
    except ImportError as exc:
        raise RuntimeError("Install PEFT dependencies with `uv pip install -r requirements-hf.txt`.") from exc
    return peft


def choose_text_device(torch_module: Any, device: str | None) -> str:
    if device:
        return device
    if torch_module.cuda.is_available():
        return "cuda"
    if getattr(torch_module.backends, "mps", None) and torch_module.backends.mps.is_available():
        return "mps"
    return "cpu"
