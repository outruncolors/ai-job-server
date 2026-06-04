/* FieldControls — a reusable hover-control affordance, app-agnostic.

   Wrap any "slot" (an avatar circle, or an editable field) and on hover/focus
   surface a small cluster of buttons. All actions are app-supplied callbacks —
   the component carries zero app knowledge.

     FieldControls.attach(slotEl, {
       kind: 'avatar' | 'field',     // cosmetic: placement/size of the cluster
       controls: [                   // buttons, left→right
         { id, label, title?, onClick(ctx, ui) },
         { id, label, title?, subactions: [   // expands into a sub-row on click
             { id, label, title?, onClick(ctx, ui) }, ...
         ] },
       ],
       context: () => ({...})        // lazy context passed to each onClick
     });

   Returns a handle: { el, destroy(), setControls(controls) }.

   Subactions: a control carrying a `subactions` array is a *menu* button —
   clicking it replaces the cluster with its subaction buttons plus an
   auto-appended **Cancel**. Picking a subaction runs its `onClick` then restores
   the resting controls; Cancel restores them without acting. This is a
   declarative, app-agnostic "expand into a sub-row" affordance — reuse it for
   any action that needs a confirm-style follow-up choice.

   Visibility: the cluster shows on `:hover` / `:focus-within` (so tapping a
   field input reveals it on touch). For non-focusable slots (avatar) a tap on
   the slot toggles an `.fc-open` class. */
(function () {
  function attach(slotEl, opts) {
    if (!slotEl || slotEl.__fcAttached) return slotEl && slotEl.__fcHandle;
    const kind = opts.kind || 'field';
    const context = typeof opts.context === 'function' ? opts.context : () => ({});

    // The slot becomes the positioned container for the overlay.
    const cs = getComputedStyle(slotEl);
    if (cs.position === 'static') slotEl.style.position = 'relative';
    slotEl.classList.add('fc-slot', `fc-${kind}`);

    const cluster = document.createElement('div');
    cluster.className = 'fc-cluster';
    slotEl.appendChild(cluster);

    // The resting (top-level) controls a subaction row restores to. Updated only
    // by setControls(); transient subaction rows render without touching it.
    let restingControls = opts.controls;

    function paint(controls) {
      cluster.innerHTML = '';
      (controls || []).forEach((c) => {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'fc-btn';
        if (c.subaction) btn.classList.add('fc-btn--sub');
        btn.dataset.id = c.id || '';
        btn.textContent = c.label;
        if (c.title) btn.title = c.title;
        btn.addEventListener('click', (e) => {
          e.preventDefault();
          e.stopPropagation();
          if (Array.isArray(c.subactions) && c.subactions.length) {
            paint(buildSubRow(c.subactions));
            return;
          }
          try { c.onClick && c.onClick(context(), { button: btn, slot: slotEl }); }
          catch (err) { console.error('FieldControls onClick error', err); }
          // A picked subaction collapses the row back to its resting controls.
          if (c.subaction) paint(restingControls);
        });
        cluster.appendChild(btn);
      });
    }

    // Wrap each subaction so it collapses after acting, and append a Cancel that
    // restores the resting controls without running anything.
    function buildSubRow(subactions) {
      const row = subactions.map((s) => ({ ...s, subaction: true }));
      row.push({ id: 'cancel', label: 'Cancel', title: 'Cancel', subaction: true });
      return row;
    }

    // Public: replace the resting controls (and render them now).
    function setControls(controls) {
      restingControls = controls;
      paint(restingControls);
    }

    paint(restingControls);

    // Touch: tapping a non-focusable avatar toggles the cluster.
    let tapHandler = null;
    if (kind === 'avatar') {
      tapHandler = (e) => {
        if (e.target.closest('.fc-btn')) return;
        slotEl.classList.toggle('fc-open');
      };
      slotEl.addEventListener('click', tapHandler);
    }

    const handle = {
      el: slotEl,
      setControls: setControls,
      destroy() {
        if (tapHandler) slotEl.removeEventListener('click', tapHandler);
        cluster.remove();
        slotEl.classList.remove('fc-slot', `fc-${kind}`, 'fc-open');
        delete slotEl.__fcAttached;
        delete slotEl.__fcHandle;
      },
    };
    slotEl.__fcAttached = true;
    slotEl.__fcHandle = handle;
    return handle;
  }

  window.FieldControls = { attach };
})();
