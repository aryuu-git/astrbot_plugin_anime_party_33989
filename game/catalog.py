"""Question catalog loading and deterministic selection."""

import json
from collections.abc import Iterable
from pathlib import Path
from random import Random
from typing import Any

from .models import Difficulty, Question


class QuestionCatalog:
    def __init__(self, questions: Iterable[Question], *, allow_empty=False) -> None:
        self._questions = tuple(questions)
        if not self._questions and not allow_empty:
            raise ValueError("question catalog cannot be empty")

    def add(self, question):
        if self.get(question.subject_id) is None:
            self._questions = (*self._questions, question)

    @property
    def size(self) -> int:
        return len(self._questions)

    @property
    def questions(self) -> tuple[Question, ...]:
        return self._questions

    def get(self, subject_id: int) -> Question | None:
        """Return one question by Bangumi subject ID."""

        return next(
            (question for question in self._questions if question.subject_id == subject_id),
            None,
        )

    def choose(
        self,
        *,
        difficulty: Difficulty,
        excluded_subject_ids: set[int],
        random: Random,
        previous_subject_id: int | None = None,
    ) -> Question:
        matching = [item for item in self._questions if item.difficulty is difficulty]
        if not matching:
            matching = list(self._questions)
        fresh = [item for item in matching if item.subject_id not in excluded_subject_ids]
        fallback = [q for q in matching if q.subject_id != previous_subject_id]
        return random.choice(fresh or fallback or matching)


def load_questions(path: Path) -> QuestionCatalog:
    if path.stat().st_size > 5 * 1024 * 1024:
        raise ValueError("question pack exceeds 5 MiB")
    raw: Any = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(raw, list) or not 1 <= len(raw) <= 5000:
        raise ValueError("question file must contain 1 to 5000 questions")

    questions: list[Question] = []
    seen = set()
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("each question must be an object")
        if type(item.get("subject_id")) is not int or item["subject_id"] <= 0:
            raise ValueError("subject_id must be a positive integer")
        if item["subject_id"] in seen:
            raise ValueError("duplicate subject_id in question pack")
        seen.add(item["subject_id"])
        for key in ("title", "emoji", "explanation"):
            if not isinstance(item.get(key), str) or not item[key].strip() or len(item[key]) > 1000:
                raise ValueError(f"{key} must be non-empty text of at most 1000 characters")
        if not isinstance(item.get("aliases"), list) or any(
            not isinstance(a, str) or not a.strip() or len(a) > 200 for a in item["aliases"]
        ):
            raise ValueError("aliases must be a list of non-empty names")
        hints = item.get("hints")
        if (
            not isinstance(hints, list)
            or len(hints) != 3
            or any(not isinstance(h, str) or not h.strip() or len(h) > 1000 for h in hints)
        ):
            raise ValueError("each question must contain exactly three hints")
        questions.append(
            Question(
                subject_id=int(item["subject_id"]),
                title=str(item["title"]),
                aliases=tuple(str(alias) for alias in item["aliases"]),
                emoji=str(item["emoji"]),
                difficulty=Difficulty(item["difficulty"]),
                hints=(str(hints[0]), str(hints[1]), str(hints[2])),
                explanation=str(item["explanation"]),
            )
        )
    return QuestionCatalog(questions)
