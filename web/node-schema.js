// Graph structure comes from the CLI's LangGraph builder. The canvas owns only
// presentation metadata and the initial geometry.
async function readGraph() {
  try {
    const response = await fetch('/api/workflow-schema');
    if (!response.ok) throw new Error('Could not read workflow schema');
    return await response.json();
  } catch (error) {
    document.getElementById('startup-error').hidden = false;
    throw error;
  }
}
const graph = await readGraph();

export const categories = {
  source: { color: 'var(--node-source)' },
  language: { color: 'var(--node-language)' },
  audio: { color: 'var(--node-audio)' },
  media: { color: 'var(--node-media)' },
};

const presentation = {
  probe_input: ['视频输入', 'source', '输入视频', '媒体信息'],
  asr_diarize: ['转写与说话人', 'source', '输入视频', '英文分段'],
  build_blocks: ['翻译分块与术语', 'language', '英文分段', '翻译块与术语表'],
  translate_blocks: ['翻译智能体', 'language', '翻译块', '初译中文字幕'],
  review_blocks: ['审校智能体', 'language', '初译结果', '审校后中文字幕'],
  tts_align: ['配音与对齐', 'audio', '审校结果', '配音音轨'],
  subtitle_cover: ['字幕压制准备', 'media', '审校译文、英文分段与画面尺寸', '三份 SRT 与烧录 ASS'],
  compose_video: ['合成视频', 'media', '源视频、烧录字幕与音轨', '成片 MP4'],
};

const initialLayout = {
  probe_input: [-828.67, 149.25, 333],
  asr_diarize: [-151.18, 132.66, 362],
  build_blocks: [404.75, 82.72, 423],
  translate_blocks: [987.59, 95.95, 429],
  review_blocks: [1508.67, 108.94, 282],
  tts_align: [2095.30, -338.91, 282],
  subtitle_cover: [2564.34, 171.28, 282],
  compose_video: [2992.75, -314.62, 282],
};

export const schema = graph.nodes.map((id, index) => {
  const [title, category, input, output] = presentation[id] ?? [id, 'media', '上游输入', '节点输出'];
  return { id, title, category, input, output, symbol: String(index + 1).padStart(2, '0') };
});
export const edges = graph.edges;

export const defaults = () => Object.fromEntries(schema.map(({ id }, index) => {
  const [x, y, width] = initialLayout[id] ?? [4400 + index * 360, 162, 282];
  return [id, { x, y, width, height: null, collapsed: false }];
}));
