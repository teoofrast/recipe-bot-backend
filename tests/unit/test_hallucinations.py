import pytest

from receipt.infrastructure.transcription.hallucinations import remove_hallucinations


@pytest.mark.parametrize(
    "text",
    [
        # Real outputs of whisper-large-v3(-turbo) on Reels with music and no speech.
        "Спасибо.  Продолжение следует...  Субтитры создавал DimaTorzok  Продолжение следует...",
        "Субтитры сделал DimaTorzok  Субтитры создавал DimaTorzok  Субтитры подогнал «Симон»!",
        "Редактор субтитров А.Синецкая Корректор А.Егорова",
        "ДИНАМИЧНАЯ МУЗЫКА",
        "Thank you for watching!",
        "Subtitles by the Amara.org community",
    ],
)
def test_known_hallucinations_are_removed(text: str) -> None:
    assert remove_hallucinations(text) in ("", "Спасибо.")


def test_real_speech_is_kept() -> None:
    speech = (
        "Всем привет! Творог отжимаю через марлю, чтобы сделать его посуше. "
        "Добавляю целое яйцо, сметану. Спасибо, что дочитали рецепт."
    )

    assert remove_hallucinations(speech) == speech


def test_hallucination_at_the_end_of_real_speech_is_cut_off() -> None:
    text = "Жарим сырники по 2 минуты с каждой стороны.  Субтитры сделал DimaTorzok"

    assert remove_hallucinations(text) == "Жарим сырники по 2 минуты с каждой стороны."
