const state = {
  snapshot: null,
  tasks: [],
  blockedTask: null,
  evidenceTarget: null,
  health: null,
};

const elements = {
  syncStatus: document.getElementById('syncStatus'),
  syncTime: document.getElementById('syncTime'),
  activeCount: document.getElementById('activeCount'),
  primaryTaskTitle: document.getElementById('primaryTaskTitle'),
  primaryTaskMeta: document.getElementById('primaryTaskMeta'),
  flowCount: document.getElementById('flowCount'),
  taskRail: document.getElementById('taskRail'),
  blockedZone: document.getElementById('blockedZone'),
  blockedTask: document.getElementById('blockedTask'),
  blockedTaskTitle: document.getElementById('blockedTaskTitle'),
  nextActionTitle: document.getElementById('nextActionTitle'),
  nextActionBasis: document.getElementById('nextActionBasis'),
  nextPriority: document.getElementById('nextPriority'),
  sourceCaption: document.getElementById('sourceCaption'),
  detailLayer: document.getElementById('detailLayer'),
  detailStatus: document.getElementById('detailStatus'),
  detailTitle: document.getElementById('detailTitle'),
  detailAgent: document.getElementById('detailAgent'),
  detailCollaborator: document.getElementById('detailCollaborator'),
  detailEvidence: document.getElementById('detailEvidence'),
  detailUpdatedAt: document.getElementById('detailUpdatedAt'),
  openEvidenceButton: document.getElementById('openEvidenceButton'),
};

function postToHost(type, payload = {}) {
  if (window.chrome?.webview) {
    window.chrome.webview.postMessage({ type, ...payload });
    return true;
  }
  return false;
}

function formatTime(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '--:--';
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(date).replace('/', '.');
}

function formatFullTime(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '未登记';
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(date).replaceAll('/', '.');
}

function compactEvidence(value) {
  if (!value) return '尚未登记证据';
  const first = String(value).split(';')[0].trim();
  const normalized = first.replaceAll('\\', '/');
  const last = normalized.split('/').filter(Boolean).at(-1);
  return last || first;
}

function taskRank(task) {
  const title = String(task.task || '');
  if (title.includes('高保真桌面工作台') || title.includes('WebView2')) return 0;
  if (String(task.agent || '').includes('Codex Desktop')) return 1;
  return 2;
}

function render(snapshot, health = null) {
  state.snapshot = snapshot;
  state.health = health;
  const activeTasks = (snapshot.current_tasks || [])
    .filter(task => ['active', 'waiting', 'blocked', 'handoff', '进行中', '等待用户确认', '受阻', '待接手'].includes(task.status))
    .sort((left, right) => taskRank(left) - taskRank(right));
  state.tasks = activeTasks.slice(0, 4);
  state.blockedTask = (snapshot.current_tasks || []).find(task => task.blocked || ['blocked', '受阻'].includes(task.status)) || null;

  const primary = state.tasks[0];
  elements.activeCount.textContent = String(activeTasks.length);
  elements.flowCount.textContent = `${state.tasks.length} 项`;
  const integration = snapshot.integration || {};
  const healthStatus = health?.status || 'live';
  document.querySelector('.workbench').dataset.sync = healthStatus;
  if (healthStatus === 'error') {
    elements.syncStatus.textContent = '正式源刷新异常';
  } else if ((integration.stale_source_count || 0) > 0) {
    elements.syncStatus.textContent = `${integration.stale_source_count} 项来源待更新`;
    document.querySelector('.workbench').dataset.sync = 'stale';
  } else {
    elements.syncStatus.textContent = 'Obsidian 正式源实时连接';
  }
  elements.syncTime.textContent = formatTime(health?.checked_at || snapshot.generated_at);
  elements.sourceCaption.textContent = `${integration.source_count ?? 0} 个正式源 · ${snapshot.metrics?.open_tasks ?? 0} 条开放任务`;

  if (primary) {
    elements.primaryTaskTitle.textContent = primary.task;
    elements.primaryTaskMeta.textContent = `${primary.status} · ${primary.agent || '执行主体待登记'}`;
  } else {
    elements.primaryTaskTitle.textContent = '当前没有登记为进行中的任务';
    elements.primaryTaskMeta.textContent = '请先在协同看板登记真实主线';
  }

  elements.taskRail.replaceChildren(...state.tasks.map((task, index) => createTaskButton(task, index)));
  if (!state.tasks.length) {
    const empty = document.createElement('p');
    empty.className = 'load-error';
    empty.textContent = '事实快照中没有可展示的进行中任务。';
    elements.taskRail.append(empty);
  }

  if (state.blockedTask) {
    elements.blockedZone.hidden = false;
    elements.blockedTaskTitle.textContent = state.blockedTask.task;
    elements.blockedTask.onclick = () => openDetail(state.blockedTask);
  } else {
    elements.blockedZone.hidden = true;
  }

  const recommendation = (snapshot.recommendations || [])[0];
  if (recommendation) {
    elements.nextActionTitle.textContent = recommendation.next_action || recommendation.recommendation;
    elements.nextActionBasis.textContent = recommendation.basis || '来自当前事实快照';
    elements.nextPriority.textContent = recommendation.priority || 'P0';
  } else if (primary?.next_action) {
    elements.nextActionTitle.textContent = primary.next_action;
    elements.nextActionBasis.textContent = '来自当前任务的已登记下一步';
    elements.nextPriority.textContent = 'NEXT';
  }
}

function createTaskButton(task, index) {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'task-item';
  button.title = task.task;
  button.addEventListener('click', () => openDetail(task));

  const copy = document.createElement('span');
  const sequence = document.createElement('span');
  sequence.className = 'task-sequence';
  sequence.textContent = `FLOW / ${String(index + 1).padStart(2, '0')}`;
  const title = document.createElement('strong');
  title.className = 'task-title';
  title.textContent = task.task;
  const meta = document.createElement('span');
  meta.className = 'task-meta';
  const agent = document.createElement('b');
  agent.textContent = task.agent || '待登记';
  const separator = document.createElement('i');
  const evidence = document.createElement('span');
  evidence.textContent = compactEvidence(task.evidence);
  meta.append(agent, separator, evidence);
  copy.append(sequence, title, meta);

  const status = document.createElement('span');
  status.className = 'task-state';
  status.textContent = task.status;
  button.append(copy, status);
  return button;
}

function openDetail(task) {
  state.evidenceTarget = (task.evidence_targets || []).find(target => target.exists) || task.source_target || null;
  elements.detailStatus.textContent = task.status || '任务状态';
  elements.detailTitle.textContent = task.task || '未命名任务';
  elements.detailAgent.textContent = task.agent || '—';
  elements.detailCollaborator.textContent = task.collaborator || '—';
  elements.detailEvidence.textContent = task.evidence || '尚未登记证据';
  elements.detailUpdatedAt.textContent = formatFullTime(state.evidenceTarget?.modified_at || state.snapshot?.generated_at);
  elements.openEvidenceButton.disabled = !state.evidenceTarget?.path;
  elements.detailLayer.classList.add('open');
  elements.detailLayer.setAttribute('aria-hidden', 'false');
  document.getElementById('detailClose').focus();
}

function closeDetail() {
  elements.detailLayer.classList.remove('open');
  elements.detailLayer.setAttribute('aria-hidden', 'true');
}

async function loadSnapshot() {
  try {
    const timestamp = Date.now();
    const response = await fetch(`data/operations_snapshot.json?ts=${timestamp}`, { cache: 'no-store' });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    let health = null;
    try {
      const healthResponse = await fetch(`data/integration_health.json?ts=${timestamp}`, { cache: 'no-store' });
      if (healthResponse.ok) health = await healthResponse.json();
    } catch (_) {
      health = null;
    }
    render(await response.json(), health);
  } catch (error) {
    elements.syncStatus.textContent = '事实快照读取失败';
    elements.primaryTaskTitle.textContent = '无法读取本地任务数据';
    elements.primaryTaskMeta.textContent = String(error);
    elements.taskRail.innerHTML = '<p class="load-error">请运行刷新脚本后重试；界面不会用演示数据替代真实任务。</p>';
  }
}

document.getElementById('refreshButton').addEventListener('click', () => {
  elements.syncStatus.textContent = '正在重建只读快照';
  document.querySelector('.workbench').dataset.sync = 'starting';
  if (!postToHost('refresh')) loadSnapshot();
});
document.getElementById('dockButton').addEventListener('click', () => postToHost('dock-right'));
document.getElementById('closeButton').addEventListener('click', () => postToHost('close'));
document.getElementById('detailClose').addEventListener('click', closeDetail);
document.getElementById('detailBackdrop').addEventListener('click', closeDetail);
elements.openEvidenceButton.addEventListener('click', () => {
  const target = state.evidenceTarget;
  if (!target?.path) return;
  if (!postToHost('open-evidence', { path: target.path }) && target.uri) {
    window.location.href = target.uri;
  }
});
document.addEventListener('keydown', event => {
  if (event.key === 'Escape') closeDetail();
});

const dragHandle = document.querySelector('.drag-handle');
let dragStart = null;
dragHandle.addEventListener('pointerdown', event => {
  dragStart = { x: event.screenX, y: event.screenY };
  dragHandle.setPointerCapture(event.pointerId);
  postToHost('drag-start');
});
dragHandle.addEventListener('pointermove', event => {
  if (!dragStart) return;
  postToHost('drag-move', { dx: event.screenX - dragStart.x, dy: event.screenY - dragStart.y });
});
dragHandle.addEventListener('pointerup', event => {
  if (!dragStart) return;
  dragHandle.releasePointerCapture(event.pointerId);
  dragStart = null;
  postToHost('drag-end');
});

window.memoryHub = { reloadData: loadSnapshot };
loadSnapshot();
