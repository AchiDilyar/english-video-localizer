import pytest
from nodes.translate_blocks._text_model import validate_chinese_translation,validate_items


@pytest.mark.parametrize('text',[
    'That white hot space people think is the biggest thing but it is small.',
    'I plan forever.','Mm -hmm.','Right.','Intelligence is not a tribute to color.',
])
def test_english_leak_is_rejected_even_when_id_is_valid(text):
    with pytest.raises(ValueError,match='TRANSLATION_LANGUAGE_MISMATCH'):
        validate_items({'items':[{'segment_id':'seg_0001','zh_subtitle':text}]},'blk_0001',['seg_0001'])


@pytest.mark.parametrize('text',['很高兴见到你','Jay-Z','The New York Times','在 Roc Nation 工作'])
def test_chinese_and_proper_names_are_allowed(text):
    validate_chinese_translation(text)
