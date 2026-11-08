import loguru
import pytest
from pydantic import ValidationError

from shinar.core import (
    LanguageEnum,
    LearningMaterial,
    Message,
    MessageRole,
    PracticeInstruction,
    PracticePlan,
    PracticeSession,
    ProficiencyLevel,
    UserProfile,
)


def test_user_profile_defaults_learner_level_to_unknown() -> None:
    profile = UserProfile(
        native_language=LanguageEnum.ENGLISH,
        target_language=LanguageEnum.JAPANESE,
    )

    assert profile.learner_level is ProficiencyLevel.UNKNOWN


def test_user_profile_requires_target_language() -> None:
    with pytest.raises(ValidationError):
        UserProfile(native_language=LanguageEnum.ENGLISH)


def test_user_profile_has_generated_id() -> None:
    profile = UserProfile(
        native_language=LanguageEnum.ENGLISH,
        target_language=LanguageEnum.JAPANESE,
    )

    assert profile.id.startswith("user_")


def test_user_profile_rejects_invalid_language_value() -> None:
    with pytest.raises(ValidationError):
        UserProfile(
            native_language="English",
            target_language=LanguageEnum.JAPANESE,
        )


def test_user_profile_goals_default_is_not_shared() -> None:
    first = UserProfile(
        native_language=LanguageEnum.ENGLISH,
        target_language=LanguageEnum.JAPANESE,
    )
    second = UserProfile(
        native_language=LanguageEnum.ENGLISH,
        target_language=LanguageEnum.JAPANESE,
    )

    first.goals.append("Practice travel conversation")

    assert second.goals == []


def test_learning_material_rejects_blank_content():
    with pytest.raises(ValidationError):
        LearningMaterial(
            title="Market trip",
            source_language=LanguageEnum.CHINESE,
            content="   ",
        )


def test_language_enum_fields_remain_enums():
    material = LearningMaterial(
        title="Market trip",
        source_language=LanguageEnum.CHINESE,
        content="Yesterday I went to the market.",
    )

    assert material.source_language is LanguageEnum.CHINESE


def test_message_rejects_blank_content():
    with pytest.raises(ValidationError):
        Message(role=MessageRole.USER, content=" ")


def test_domain_models_forbid_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        LearningMaterial(
            title="Market trip",
            source_language=LanguageEnum.CHINESE,
            content="Yesterday I went to the market.",
            unknown_field=True,
        )


def test_practice_session_current_instruction_returns_latest_instruction() -> None:
    first = PracticeInstruction(prompt="Introduce yourself.")
    second = PracticeInstruction(prompt="Retell the material.")
    session = PracticeSession(
        material_id="mat_1",
        pattern_id="guided_roleplay",
        profile={
            "profile_level": ProficiencyLevel.A2,
            "native_language": LanguageEnum.CHINESE,
            "target_language": LanguageEnum.ENGLISH,
        },
        plan=PracticePlan(
            pattern_id="guided_roleplay",
            title="Market trip practice",
            instructions=[first, second],
        ),
    )

    assert session.current_instruction == second
