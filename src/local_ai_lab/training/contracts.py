from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Sequence


@dataclass(frozen=True, slots=True)
class TrainingContractReport:
    c1_assistant_only_loss: bool
    c2_supervised_eos: bool
    c3_same_chat_template: bool
    c4_assistant_not_truncated: bool
    c5_padding_outside_loss: bool
    c6_seed_and_nondeterminism_recorded: bool
    errors: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return all(
            (
                self.c1_assistant_only_loss, self.c2_supervised_eos,
                self.c3_same_chat_template, self.c4_assistant_not_truncated,
                self.c5_padding_outside_loss, self.c6_seed_and_nondeterminism_recorded,
            )
        )

    def as_dict(self) -> dict[str, Any]:
        return {**asdict(self), "passed": self.passed}


class TrainingContractValidator:
    def validate(
        self,
        examples: Sequence[dict[str, Any]],
        *,
        expected_template_fingerprint: str,
        seed: int | None,
        nondeterminism_notes: Sequence[str],
    ) -> TrainingContractReport:
        errors: list[str] = []
        c1 = c2 = c3 = c4 = c5 = bool(examples)
        for index, example in enumerate(examples):
            input_ids = example.get("input_ids")
            labels = example.get("labels")
            attention = example.get("attention_mask")
            assistant_start = example.get("assistant_start")
            eos = example.get("eos_token_id")
            pad = example.get("pad_token_id")
            if not (
                isinstance(input_ids, list) and isinstance(labels, list) and isinstance(attention, list)
                and len(input_ids) == len(labels) == len(attention) and isinstance(assistant_start, int)
                and 0 <= assistant_start < len(input_ids)
            ):
                errors.append(f"example {index}: invalid token arrays or assistant boundary")
                c1 = c2 = c4 = c5 = False
                continue
            if any(label != -100 for label in labels[:assistant_start]) or not any(
                label != -100 for label in labels[assistant_start:]
            ):
                c1 = False
                errors.append(f"example {index}: loss is not restricted to assistant tokens")
            if eos is None or eos not in [label for label in labels[assistant_start:] if label != -100]:
                c2 = False
                errors.append(f"example {index}: supervised assistant EOS is missing")
            if example.get("template_fingerprint") != expected_template_fingerprint:
                c3 = False
                errors.append(f"example {index}: chat template fingerprint differs")
            active_tokens = [token for token, mask in zip(input_ids, attention) if mask == 1]
            if example.get("assistant_truncated") is not False or not active_tokens or active_tokens[-1] != eos:
                c4 = False
                errors.append(f"example {index}: assistant was truncated or does not end in EOS")
            if any(mask == 0 and label != -100 for mask, label in zip(attention, labels)):
                c5 = False
                errors.append(f"example {index}: padding contributes to loss")
            if pad is not None and any(
                token == pad and mask == 0 and label != -100
                for token, mask, label in zip(input_ids, attention, labels)
            ):
                c5 = False
                errors.append(f"example {index}: pad token is supervised")
        c6 = isinstance(seed, int) and bool(nondeterminism_notes) and all(
            isinstance(note, str) and note.strip() for note in nondeterminism_notes
        )
        if not c6:
            errors.append("seed and explicit nondeterminism notes are required")
        return TrainingContractReport(c1, c2, c3, c4, c5, c6, tuple(errors))
