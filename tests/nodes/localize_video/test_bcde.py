import pytest
from contracts import GraphState
from nodes.localize_video.pipeline import StageServices,build_bcde_graph
from nodes.localize_video.common import run_nodes


def test_four_stages_merge_existing_contract_fields_in_order():
    order=[]
    def step(name):
        def node(state):
            assert state.terminology==({n:n for n in order} if order else None)
            order.append(name)
            return {'terminology':{n:n for n in order}}
        return node
    services=StageServices(b_nodes=(step('B'),),c_nodes=(step('C'),),d_nodes=(step('D'),),e_nodes=(step('E'),))
    initial=GraphState(input_video='input.mp4')
    result=build_bcde_graph(services).invoke(initial)
    assert order==['B','C','D','E'] and result['terminology']=={n:n for n in order}
    assert initial.terminology is None


def test_stage_rejects_undocumented_shared_state_fields():
    with pytest.raises(ValueError,match='GraphState delta'):
        run_nodes(GraphState(input_video='input.mp4'),[lambda state:{'secret_extra_field':True}])


def test_default_stage_switches_remain_owned_by_f_mock_config(monkeypatch):
    from nodes.localize_video.common import resolve_stage_nodes
    monkeypatch.setattr('graph.registry.load_node_modes',lambda:{'probe_input':'mock'})
    nodes=resolve_stage_nodes(('probe_input',))
    assert nodes[0].__module__=='mocks.probe_input'


def test_b_environment_publication_is_bound_to_source(tmp_path):
    from nodes.localize_video.b_source import publish_environment
    from nodes.background_audio import digest
    source=tmp_path/'input.mp4';source.write_bytes(b'source')
    bed=tmp_path/'bed.wav';bed.write_bytes(b'prepared-bed')
    output=tmp_path/'environment.wav'
    evidence={'source_sha256':digest(source),'environment_sha256':digest(bed)}
    assert publish_environment(source,bed,output,evidence)==output and output.read_bytes()==bed.read_bytes()
    source.write_bytes(b'other-source')
    with pytest.raises(ValueError,match='evidence'):publish_environment(source,bed,output,evidence)


def test_c_stage_keeps_f_incremental_repair_in_the_order(monkeypatch):
    from nodes.localize_video import c_content
    seen=[]
    def resolve(names):
        seen.extend(names);return (lambda state:{},)
    monkeypatch.setattr(c_content,'resolve_stage_nodes',resolve)
    assert c_content.run_c(GraphState())=={}
    assert seen==['build_blocks','translate_blocks','review_blocks','repair_blocks']


def test_selected_incremental_node_still_uses_f_exception_proxy(monkeypatch):
    from nodes.localize_video.common import resolve_stage_nodes
    import nodes.repair_blocks as repair
    monkeypatch.setattr('graph.registry.load_node_modes',lambda:{'repair_blocks':'real'})
    def broken(state):raise RuntimeError('simulated repair outage')
    monkeypatch.setattr(repair,'repair_blocks',broken)
    assert resolve_stage_nodes(('repair_blocks',))[0](GraphState())=={}


def test_d_prefers_optional_repair_without_mutating_reviewed_state(monkeypatch):
    from dataclasses import replace
    from contracts import Segment,TranslatedSegment
    import nodes.tts_align as tts
    monkeypatch.setattr(tts,'load_voice_plan',lambda:replace(tts.build_voice_plan({}),natural_groups=True))
    draft=TranslatedSegment(segment_id='seg_0001',block_id='blk_0001',zh_subtitle='初稿')
    repaired=draft.model_copy(update={'zh_subtitle':'返工稿'})
    state=GraphState(segments=[Segment(segment_id='seg_0001',speaker_id='spk_1',start_ms=0,end_ms=1000,text_en='Hello.')],reviewed_blocks=[draft],repaired_blocks=[repaired])
    seen=[]
    def synthesis(state,*args):seen.extend(s.zh_subtitle for s in state.reviewed_blocks);return {}
    monkeypatch.setattr('nodes.natural_dubbing.synthesize_groups',synthesis)
    assert tts.tts_align(state)=={} and seen==['返工稿']
    assert state.reviewed_blocks[0].zh_subtitle=='初稿'
