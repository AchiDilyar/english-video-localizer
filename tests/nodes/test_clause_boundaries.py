from nodes.subtitle_paging import clauses

def test_finite_clauses_and_literal_coverage():
    text='I believe that we can do better and we should try again.'
    parts=clauses(text)
    assert ''.join(parts)==text
    assert any(p.startswith('that ') for p in parts)
    assert any(p.startswith('and ') for p in parts)

def test_nominal_and_demonstrative_not_split():
    for text in ['I like cats and dogs.', 'I bought that book yesterday.', 'They bought and sold stocks.']:
        assert clauses(text)==[text]

def test_parallel_infinitive_clauses_can_split():
    text="We want to teach compassion and to identify with everyone's struggle and to know their stories."
    parts=clauses(text)
    assert ''.join(parts)==text and len(parts)==3
    assert parts[1].startswith('and to identify')
