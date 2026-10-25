export function intervals(failures, duration) {
  if (!Number.isFinite(duration) || duration <= 0) return [];
  return (Array.isArray(failures) ? failures : []).flatMap((failure, index) => {
    const start = failure.t_start_s, end = failure.t_end_s;
    if (!Number.isFinite(start) || !Number.isFinite(end) || start < 0 || end < start || start >= duration) return [];
    return [{failure, index, start, end: Math.min(end, duration)}];
  });
}

export function mountFailureTimeline(host, video, failures, describe, onSelect=()=>{}, summary='') {
  const doc = host.ownerDocument;
  let disposed = false;
  let selected = null;
  function seekFinished() {
    if (disposed || !selected) return;
    const matched = Math.abs(video.currentTime - selected.start) < 0.08;
    selection.textContent = matched
      ? `Selected: ${describe(selected.failure)} · ${video.currentTime.toFixed(2)}s seek complete`
      : 'Video segment seek failed · The actual playback position differs from the requested time.';
  }
  const buttons = [];
  const label = doc.createElement('p');
  label.textContent = summary || 'Red: detection error · Yellow: insufficient comparison evidence. Select a segment to jump to that time. Unmarked segments are not judged normal.';
  host.replaceChildren(label);
  const selection = doc.createElement('p');
  selection.setAttribute('role', 'status');
  function render() {
    if (disposed) return;
    buttons.length = 0;
    host.replaceChildren(label);
    const rows = intervals(failures, video.duration);
    if (!rows.length) {
      selection.textContent = failures?.length ? 'No error segment can be matched against the video length.' : 'No confirmed error segment · This does not mean the whole video is normal.';
      host.append(selection);
      return;
    }
    selection.textContent = 'Comparison ready · Select a segment to jump to that scene.';
    for (const row of rows) {
      const button = doc.createElement('button');
      button.type = 'button';
      button.textContent = describe(row.failure);
      button.setAttribute('aria-pressed', 'false');
      const track = doc.createElement('span');
      track.style.cssText = 'display:block;position:relative;height:8px;background:#293543;margin:5px 0';
      const segment = doc.createElement('span');
      segment.style.cssText = `position:absolute;height:100%;background:${row.failure.type==='OBSERVATION_GAP'?'#e4b747':'#ed7777'};min-width:2px;left:${row.start / video.duration * 100}%;width:${(row.end - row.start) / video.duration * 100}%`;
      track.append(segment);
      button.append(track);
      button.onclick = () => {
        if (disposed || video.readyState < 1) return;
        selected = row;
        video.pause();
        onSelect(row.failure,row.start);
        selection.textContent = `Selected: ${describe(row.failure)} · Seeking video`;
        video.currentTime = row.start;
        for (const other of buttons) other.setAttribute('aria-pressed', String(other === button));
        if (!video.seeking) seekFinished();
      };
      buttons.push(button);
      host.append(button);
    }
    host.append(selection);
  }
  selection.textContent = 'Checking the comparison video length.';
  host.append(selection);
  video.addEventListener('loadedmetadata', render);
  video.addEventListener('seeked', seekFinished);
  if (video.readyState >= 1) render();
  return () => { disposed = true; video.removeEventListener('loadedmetadata', render); video.removeEventListener('seeked', seekFinished); host.replaceChildren(); };
}

// Keep the draft panel tied to the same selection as the Guard panel.
export function createDraftView(panel, video, download) {
  let current = 0;
  function clear() {
    panel.hidden = true;
    video.pause();
    video.removeAttribute('src');
    video.load();
    download.removeAttribute('href');
    delete panel.dataset.runId;
  }
  return {
    begin(epoch) { current = epoch; clear(); },
    show(run, state, epoch) {
      if (epoch !== current) return false;
      clear();
      if (!/^t3-[a-f0-9]{32}$/.test(run) ||
          (state.status !== 'succeeded' && state.draft_available !== true)) return false;
      video.src = `/results/${run}/${state.draft_comparison_available===false?'generated':'comparison'}.mp4?preview=1`;
      panel.dataset.comparison = state.draft_comparison_available===false?'draft-only':'reference-draft';
      download.href = `/results/${run}/generated.mp4?preview=1`;
      panel.dataset.runId = run;
      panel.hidden = false;
      return true;
    }
  };
}
