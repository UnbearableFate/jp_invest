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


BASE_MODEL = 'ProsusAI/finbert'
TRAIN_CSV = 'data/hf_text_labels.csv'
HUB_MODEL_ID = 'your-hf-name/jp-finance-sentiment-lora'
TEXT_COLUMN = 'text'
LABEL_COLUMN = 'label'
NUM_LABELS = 3
MAX_LENGTH = 256


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
        r=16,
        lora_alpha=32,
        lora_dropout=0.05,
        bias="none",
        modules_to_save=["classifier"],
    )
    model = get_peft_model(model, peft_config)
    model.print_trainable_parameters()

    args = TrainingArguments(
        output_dir="hf_finance_peft",
        learning_rate=0.0002,
        per_device_train_batch_size=16,
        per_device_eval_batch_size=16,
        num_train_epochs=3,
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
