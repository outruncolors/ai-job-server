/* Tomeberry shared state + API helpers. Everything hangs off window.TB. */
(function () {
  const base = '/apps/tomeberry';

  const TB = {
    tale: null,
    hierarchy: null,
    concepts: [],
    currentUnitId: null,
    mode: 'draft',
    savedPromptKey: '',
    activePane: 'content',     // content | organization
    leftTab: 'content',
    pendingProposal: null,     // { request_id, target_concept_id, scope, status }
    assistant: { messages: [] },
    selection: null,           // { selected_text, char_range:[a,b] }
  };

  // Mode groups for the topbar selector (B7).
  TB.MODE_GROUPS = [
    ['Create', ['discover', 'draft', 'develop']],
    ['Shape', ['organize', 'revise', 'plan']],
    ['Check', ['edit', 'diagnose', 'track']],
    ['Finish', ['publish']],
  ];

  // ---- api wrappers --------------------------------------------------------
  TB.api = {
    listTales: () => api(`${base}/tales`),
    createTale: (body) => api(`${base}/tales`, 'POST', body),
    getTale: (tid) => api(`${base}/tales/${tid}`),
    patchTale: (tid, body) => api(`${base}/tales/${tid}`, 'PATCH', body),
    deleteTale: (tid) => api(`${base}/tales/${tid}`, 'DELETE'),
    setPremise: (tid, body) => api(`${base}/tales/${tid}/premise`, 'PUT', { body }),
    listConcepts: (tid, q = '') => api(`${base}/tales/${tid}/concepts${q}`),
    createConcept: (tid, body) => api(`${base}/tales/${tid}/concepts`, 'POST', body),
    getConcept: (tid, cid) => api(`${base}/tales/${tid}/concepts/${cid}`),
    patchConcept: (tid, cid, body) => api(`${base}/tales/${tid}/concepts/${cid}`, 'PATCH', body),
    deleteConcept: (tid, cid) => api(`${base}/tales/${tid}/concepts/${cid}`, 'DELETE'),
    hierarchy: (tid) => api(`${base}/tales/${tid}/hierarchy`),
    move: (tid, cid, body) => api(`${base}/tales/${tid}/concepts/${cid}/move`, 'POST', body),
    addLink: (tid, cid, body) => api(`${base}/tales/${tid}/concepts/${cid}/links`, 'POST', body),
    removeLink: (tid, cid, rel, target) =>
      api(`${base}/tales/${tid}/concepts/${cid}/links/${encodeURIComponent(rel)}/${encodeURIComponent(target)}`, 'DELETE'),
    request: (tid, body) => api(`${base}/tales/${tid}/requests`, 'POST', body),
    accept: (tid, rid) => api(`${base}/tales/${tid}/requests/${rid}/accept`, 'POST'),
    reject: (tid, rid) => api(`${base}/tales/${tid}/requests/${rid}/reject`, 'POST'),
    iterate: (tid, rid, text) => api(`${base}/tales/${tid}/requests/${rid}/iterate`, 'POST', { text }),
    assistant: (tid) => api(`${base}/tales/${tid}/assistant`),
    requests: (tid) => api(`${base}/tales/${tid}/requests`),
    requestDetail: (tid, rid) => api(`${base}/tales/${tid}/requests/${rid}`),
    proposal: (tid, diffId) => api(`${base}/tales/${tid}/proposals/${diffId}`),
    savedPrompts: () => api('/prompt-pal/entries?app=tomeberry').catch(() => ({ entries: [] })),
  };

  TB.conceptById = (id) => TB.concepts.find((c) => c.id === id) || null;
  TB.currentUnit = () => (TB.currentUnitId ? TB.conceptById(TB.currentUnitId) : null);

  TB.refreshConcepts = async () => {
    const data = await TB.api.getTale(TB.tale.id);
    TB.tale = data.tale;
    TB.hierarchy = data.hierarchy;
    TB.concepts = data.concepts || [];
  };

  window.TB = TB;
})();
