/* Organization pane — premise, structural tree, concepts, relationships. */
(function () {
  const Org = {};

  function pane() {
    return document.getElementById('tb-org-pane');
  }

  function treeNode(node, depth) {
    if (!node) return '';
    const sel = node.id === TB.currentUnitId ? 'sel' : '';
    const kids = (node.children || []).map((k) => treeNode(k, depth + 1)).join('');
    return `
      <div class="tb-unit ${sel}" style="margin-left:${depth * 14}px">
        <span class="tb-unit-type">${_escHtml(node.type)}</span>
        <span class="tb-unit-title" data-write="${_escHtml(node.id)}">${_escHtml(node.title || '(untitled)')}</span>
        <span class="tb-unit-wc">${node.word_count || 0}w</span>
        <span class="tb-unit-acts">
          <button data-add-child="${_escHtml(node.id)}" title="Add child">+</button>
          <button data-rename="${_escHtml(node.id)}" title="Rename">✎</button>
          <button data-del="${_escHtml(node.id)}" title="Delete" class="tb-danger">×</button>
        </span>
      </div>${kids}`;
  }

  function conceptRow(c) {
    const links = (c.links || []).length;
    return `
      <div class="tb-concept" data-cid="${_escHtml(c.id)}">
        <span class="tb-concept-type">${_escHtml(c.type)}</span>
        <span class="tb-concept-title" data-edit-concept="${_escHtml(c.id)}">${_escHtml(c.title || '(untitled)')}</span>
        ${links ? `<span class="tb-concept-links" title="links">🔗${links}</span>` : ''}
        <button data-del-concept="${_escHtml(c.id)}" class="tb-danger" title="Delete">×</button>
      </div>`;
  }

  Org.render = function () {
    const p = pane();
    if (!TB.tale) {
      p.innerHTML = '';
      return;
    }
    const premise = TB.conceptById(TB.tale.premise_id) || {};
    const ncs = TB.concepts.filter((c) => c.concept_class === 'narrative_construct' && c.type !== 'premise');
    const ses = TB.concepts.filter((c) => c.concept_class === 'story_entity');
    const tree = TB.hierarchy && TB.hierarchy.root ? TB.hierarchy.root : null;

    p.innerHTML = `
      <div class="tb-org-section">
        <div class="tb-org-label">Premise</div>
        <textarea id="tb-premise" rows="3" placeholder="What is this tale about?">${_escHtml(premise.body || '')}</textarea>
        <button id="tb-premise-save" class="tb-mini">Save premise</button>
      </div>

      <div class="tb-org-section">
        <div class="tb-org-label">Structure
          <button id="tb-add-chapter" class="tb-mini">+ chapter</button>
        </div>
        <div id="tb-tree">${tree ? treeNode(tree, 0) : '<div class="tb-empty">No structure yet.</div>'}</div>
      </div>

      <div class="tb-org-section">
        <div class="tb-org-label">Narrative constructs
          <button data-add-concept="narrative_construct" class="tb-mini">+ add</button>
        </div>
        <div>${ncs.length ? ncs.map(conceptRow).join('') : '<div class="tb-empty">none</div>'}</div>
      </div>

      <div class="tb-org-section">
        <div class="tb-org-label">Story entities
          <button data-add-concept="story_entity" class="tb-mini">+ add</button>
        </div>
        <div>${ses.length ? ses.map(conceptRow).join('') : '<div class="tb-empty">none</div>'}</div>
      </div>

      <div class="tb-org-section" id="tb-rel-inspector"></div>
    `;
    Org.wire();
  };

  Org.wire = function () {
    const p = pane();
    p.querySelector('#tb-premise-save').addEventListener('click', async () => {
      const body = p.querySelector('#tb-premise').value;
      await TB.api.setPremise(TB.tale.id, body);
      await TB.refreshConcepts();
      toast('success', 'Premise saved');
    });
    p.querySelector('#tb-add-chapter').addEventListener('click', () => Org.addUnit(TB.tale.structural_root_id, 'chapter'));

    p.querySelectorAll('[data-write]').forEach((el) =>
      el.addEventListener('click', () => Org.selectUnit(el.getAttribute('data-write')))
    );
    p.querySelectorAll('[data-add-child]').forEach((el) =>
      el.addEventListener('click', () => Org.addUnit(el.getAttribute('data-add-child'), 'scene'))
    );
    p.querySelectorAll('[data-rename]').forEach((el) =>
      el.addEventListener('click', () => Org.rename(el.getAttribute('data-rename')))
    );
    p.querySelectorAll('[data-del]').forEach((el) =>
      el.addEventListener('click', () => Org.delUnit(el.getAttribute('data-del')))
    );
    p.querySelectorAll('[data-add-concept]').forEach((el) =>
      el.addEventListener('click', () => Org.addConcept(el.getAttribute('data-add-concept')))
    );
    p.querySelectorAll('[data-edit-concept]').forEach((el) =>
      el.addEventListener('click', () => Org.editConcept(el.getAttribute('data-edit-concept')))
    );
    p.querySelectorAll('[data-del-concept]').forEach((el) =>
      el.addEventListener('click', () => Org.delConcept(el.getAttribute('data-del-concept')))
    );
  };

  Org.selectUnit = function (id) {
    TB.currentUnitId = id;
    TB.pendingProposal = null;
    if (TB.Topbar) TB.Topbar.render();
    if (TB.ContentPane) TB.ContentPane.render();
    if (TB.switchLeftTab) TB.switchLeftTab('content');
    Org.render();
  };

  Org.addUnit = async function (parentId, type) {
    const title = prompt(`New ${type} title:`, '');
    if (title === null) return;
    await TB.api.createConcept(TB.tale.id, {
      concept_class: 'structural_unit', type, title, parent_id: parentId,
    });
    await TB.refreshConcepts();
    Org.render();
  };

  Org.rename = async function (id) {
    const c = TB.conceptById(id);
    const title = prompt('Rename:', c ? c.title : '');
    if (title === null) return;
    await TB.api.patchConcept(TB.tale.id, id, { title });
    await TB.refreshConcepts();
    Org.render();
    if (TB.ContentPane) TB.ContentPane.render();
  };

  Org.delUnit = async function (id) {
    if (!confirm('Delete this unit and detach its children?')) return;
    await TB.api.deleteConcept(TB.tale.id, id);
    if (TB.currentUnitId === id) TB.currentUnitId = null;
    await TB.refreshConcepts();
    Org.render();
    if (TB.ContentPane) TB.ContentPane.render();
  };

  Org.addConcept = async function (cls) {
    const type = prompt(`Type (e.g. ${cls === 'story_entity' ? 'character/place/object' : 'arc/theme/plotline'}):`, cls === 'story_entity' ? 'character' : 'plotline');
    if (type === null) return;
    const title = prompt('Title:', '');
    if (title === null) return;
    await TB.api.createConcept(TB.tale.id, { concept_class: cls, type, title });
    await TB.refreshConcepts();
    Org.render();
  };

  Org.editConcept = function (id) {
    const c = TB.conceptById(id);
    if (!c) return;
    const body = prompt(`${c.title} — body:`, c.body || '');
    if (body === null) {
      Org.showLinks(id);
      return;
    }
    TB.api.patchConcept(TB.tale.id, id, { body }).then(async () => {
      await TB.refreshConcepts();
      Org.render();
    });
  };

  Org.delConcept = async function (id) {
    if (!confirm('Delete this concept?')) return;
    await TB.api.deleteConcept(TB.tale.id, id);
    await TB.refreshConcepts();
    Org.render();
  };

  Org.showLinks = function (id) {
    const c = TB.conceptById(id);
    const box = document.getElementById('tb-rel-inspector');
    if (!c || !box) return;
    box.innerHTML = `
      <div class="tb-org-label">Relationships — ${_escHtml(c.title)}
        <button id="tb-add-link" class="tb-mini">+ link</button>
      </div>
      ${(c.links || []).length ? (c.links || []).map((l) => {
        const t = TB.conceptById(l.target_id);
        return `<div class="tb-link">${_escHtml(l.rel)} → ${_escHtml(t ? t.title : l.target_id)}
          <button data-rmlink="${_escHtml(l.rel)}|${_escHtml(l.target_id)}" class="tb-danger">×</button></div>`;
      }).join('') : '<div class="tb-empty">no links</div>'}`;
    box.querySelector('#tb-add-link').addEventListener('click', async () => {
      const rel = prompt('Relationship (e.g. advances, appears_in, knows):', 'relates_to');
      if (rel === null) return;
      const opts = TB.concepts.filter((x) => x.id !== id).map((x) => `${x.id} — ${x.title}`).join('\n');
      const target = prompt('Target concept id:\n' + opts, '');
      if (!target) return;
      await TB.api.addLink(TB.tale.id, id, { rel, target_id: target.split(' ')[0] });
      await TB.refreshConcepts();
      Org.render();
      Org.showLinks(id);
    });
    box.querySelectorAll('[data-rmlink]').forEach((el) =>
      el.addEventListener('click', async () => {
        const [rel, target] = el.getAttribute('data-rmlink').split('|');
        await TB.api.removeLink(TB.tale.id, id, rel, target);
        await TB.refreshConcepts();
        Org.render();
        Org.showLinks(id);
      })
    );
  };

  window.TB = window.TB || {};
  window.TB.OrgPane = Org;
})();
