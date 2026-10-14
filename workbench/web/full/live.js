const dashboardState = {
  snapshot: null,
  records: new Map(),
  lastFocused: null,
  activeBrief: null,
};

const portfolioBuckets = [
  { key: '正在推进', label: '正在推进', tone: '' },
  { key: '等待判断', label: '等待判断', tone: 'wait' },
  { key: '待核实 / 停滞', label: '待核实 / 停滞', tone: 'verify' },
  { key: '阶段成果', label: '阶段成果', tone: 'complete' },
  { key: '新信号', label: '新信号', tone: 'signal' },
];

const domainDescriptions = {
  '经营分析与数据': '经营分析、数据底座与业务决策',
  'AI 系统与 Agent': 'Agent、数字人和本地应用',
  '产品、学习与内容': '产品、培训、学习和内容资产',
  '知识与能力建设': '知识沉淀、方法与能力建设',
  '其他项目': '未归入主要工作领域的项目',
};

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function formatDate(value, includeTime = false) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value || '未登记';
  return new Intl.DateTimeFormat('zh-CN', {
    year: includeTime ? 'numeric' : undefined,
    month: '2-digit',
    day: '2-digit',
    hour: includeTime ? '2-digit' : undefined,
    minute: includeTime ? '2-digit' : undefined,
    hour12: false,
  }).format(date).replaceAll('/', '.');
}

function compactPath(value) {
  if (!value) return '尚未登记来源';
  const normalized = String(value).replaceAll('\\', '/');
  return normalized.split('/').filter(Boolean).at(-1) || value;
}

function updateClock() {
  document.getElementById('clock').textContent = new Intl.DateTimeFormat('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(new Date());
}

function recordForProject(project) {
  const target = (project.evidence_targets || []).find(item => item.exists) || project.source_target || {};
  return {
    title: project.project,
    state: project.current_brief ? `项目：${project.current_brief.project_state} · 最新任务：${project.current_brief.task_state || '未确认'}` : project.operating_state || project.status,
    summary: project.current_brief?.preview || project.state_reason || '正式项目页暂未登记状态依据。',
    next: project.work_cycle?.suggestion?.next_step || project.current_brief?.next_action || project.decision || project.next_step || '尚未登记下一动作。',
    brief: project.current_brief,
    evidence: project.latest_evidence_date
      ? `最近正式证据 ${project.latest_evidence_date}；项目页状态：${project.page_state || '未显式登记'}；未勾选事项 ${project.unchecked_items || 0} 条。`
      : `尚未匹配到正式工作日志；项目页状态：${project.page_state || '未显式登记'}。`,
    source: target.path || project.project_page || project.path || '尚未登记来源',
    uri: target.uri || '',
  };
}

function recordForDecision(entry) {
  const target = (entry.evidence_targets || []).find(item => item.exists) || entry.source_target || {};
  return {
    title: entry.title || '未命名判断事项',
    state: entry.status || '等待判断',
    summary: entry.completed || '正式记录尚未补充本次完成。',
    next: entry.next_action || entry.unfinished || '等待确认通过、修改、继续或暂停。',
    evidence: entry.evidence || entry.key_files || '证据路径尚未登记。',
    source: target.path || entry.source || '尚未登记来源',
    uri: target.uri || '',
  };
}

function recordForLedger(ledger) {
  const target = ledger.source_target || {};
  return {
    title: ledger.title || '未命名任务总账',
    state: ledger.conserved ? '范围守恒通过' : '范围守恒异常',
    summary: `原始 ${ledger.total || 0} 项 = 完成 ${ledger.completed || 0} + 延期 ${ledger.deferred || 0} + 未闭环 ${ledger.open || 0}。`,
    next: ledger.open
      ? `继续核对 ${ledger.open} 项未闭环事项；${ledger.needs_review || 0} 项需要优先复核。`
      : '清单已闭环，保留完成和延期证据。',
    evidence: `当前阶段范围 ${ledger.current_scope ?? '未登记'} 项；元数据完成数 ${ledger.metadata_completed ?? '未登记'}；延期数 ${ledger.metadata_deferred ?? '未登记'}。`,
    source: target.path || '尚未登记来源',
    uri: target.uri || '',
  };
}

function recordForConfirmation(entry) {
  const target = (entry.evidence_targets || []).find(item => item.exists) || entry.source_target || {};
  return {
    title: entry.title || '未命名确认事项',
    state: `${entry.priority || 'P1'} · ${entry.kind || entry.status || '待确认'}`,
    summary: entry.reason || '等待人工确认。',
    next: entry.next_action || '确认继续、延期、合并或关闭。',
    evidence: `来源状态：${entry.status || '待核实'}；确认前保持只读。`,
    source: target.path || '尚未登记来源',
    uri: target.uri || '',
  };
}

function registerRecord(record) {
  const key = `record-${dashboardState.records.size + 1}`;
  dashboardState.records.set(key, record);
  return key;
}

function createProjectNode(project, tone) {
  const record = recordForProject(project);
  const key = registerRecord(record);
  const button = element('button', `project-node ${tone || ''}`.trim());
  button.type = 'button';
  button.dataset.recordKey = key;
  button.dataset.search = `${project.project} ${project.operating_state} ${record.summary} ${record.next} ${project.state_reason}`.toLowerCase();
  button.append(
    element('span', 'project-title', project.project),
    element('span', 'project-summary', record.summary),
  );
  const next = element('span', 'project-next');
  next.append(element('b', '', '→'), document.createTextNode(` ${project.work_cycle?.suggestion?.label||'下一步'}：${record.next}`));
  button.append(next, element('span', 'project-date', project.latest_evidence_date || project.status || '未核'));
  if (record.brief) button.append(element('span', 'brief-entry', project.lifecycle && project.lifecycle.state !== 'active' ? '查看摘要 / 恢复跟进 →' : '当前摘要 / 管理项目 →'));
  button.addEventListener('click', () => openDrawer(key, button));
  return button;
}

function createEmergingNode(project) {
  const record = {
    title: project.name,
    state: project.status,
    summary: project.evidence_note,
    next: project.decision,
    evidence: `最近活动 ${project.latest_activity_date || '未登记'}`,
    source: project.source || project.path,
    uri: project.source_link || '',
  };
  const key = registerRecord(record);
  const button = element('button', 'project-node state-signal');
  button.type = 'button';
  button.dataset.recordKey = key;
  button.dataset.search = `${project.name} ${project.status} ${project.decision}`.toLowerCase();
  button.append(
    element('span', 'project-title', project.name),
    element('span', 'project-summary', project.evidence_note),
  );
  const next = element('span', 'project-next');
  next.append(element('b', '', '→'), document.createTextNode(` ${project.decision}`));
  button.append(next, element('span', 'project-date', project.latest_activity_date || '新信号'));
  button.addEventListener('click', () => openDrawer(key, button));
  return button;
}

function renderDirective(snapshot) {
  const recommendation = (snapshot.recommendations || [])[0] || {};
  document.getElementById('directiveKicker').textContent = `Current directive · ${formatDate(snapshot.generated_at)}`;
  document.getElementById('directiveTitle').textContent = recommendation.recommendation || '保持唯一主线，用证据推进下一步。';
  document.getElementById('directiveSummary').textContent = recommendation.next_action || recommendation.basis || '当前没有显著判断拥堵。';
  const focus = snapshot.recent_focus || [];
  if (focus.length) {
    document.getElementById('directiveTitle').textContent = `近期重点：${focus.map(task => task.task).join('、')}`;
    document.getElementById('directiveSummary').textContent = '先查看近期重点的最新进展与证据；对话活动和正式验收分别呈现。';
  }
  document.getElementById('decisionFact').textContent = `${snapshot.confirmation_queue?.length || 0} 条人工确认 · 只读`;
  const waitingProjects = (snapshot.projects || []).filter(project => project.bucket === '等待判断').length;
  document.getElementById('directiveInference').textContent = `${waitingProjects} 个项目待确认 · ${snapshot.projects_to_verify?.length || 0} 个项目待核实`;
  document.getElementById('latestSource').textContent = formatDate(snapshot.integration?.latest_source_modified_at);
}

function renderStatusOverview(snapshot) {
  const projects = snapshot.projects || [];
  const statusDefinitions = [
    { label: '正在推进', count: projects.filter(project => project.bucket === '正在推进').length, note: '有近期正式证据', className: '' },
    { label: '项目待确认', count: projects.filter(project => project.bucket === '等待判断').length, note: '项目级判断', className: 'wait' },
    { label: '待核实', count: snapshot.projects_to_verify?.length || 0, note: '状态或证据陈旧', className: 'verify' },
    { label: '阶段成果', count: projects.filter(project => project.bucket === '阶段成果').length, note: '不等于项目结束', className: 'complete' },
    { label: '参考 / 历史', count: projects.filter(project => project.bucket === '非当前项目').length, note: `${snapshot.emerging_projects?.length || 0} 个新信号`, className: 'archive' },
  ];
  document.querySelectorAll('.status-signal').forEach((node, index) => {
    const definition = statusDefinitions[index];
    if (!definition) return;
    node.className = `status-signal ${definition.className}`.trim();
    node.querySelector('.status-count').textContent = String(definition.count);
    node.querySelector('.status-name').textContent = definition.label;
    node.querySelector('.status-note').textContent = definition.note;
  });
}

function renderSources(snapshot) {
  const ribbon = document.getElementById('sourceRibbon');
  const sources = snapshot.sources || [];
  ribbon.className = 'source-ribbon live-data';
  ribbon.style.setProperty('--source-count', Math.max(sources.length, 1));
  const intro = element('div', 'source-intro');
  intro.append(
    element('strong', '', snapshot.integration?.stale_source_count ? '来源新鲜度提醒' : '正式来源已连接'),
    element('span', '', `${sources.length} 个正式来源 · ${snapshot.integration?.stale_source_count || 0} 个超过新鲜度阈值`),
  );
  const items = sources.map(source => {
    const item = element('div', `source-item${source.stale ? ' stale' : ''}`);
    const name = element('div', 'source-name');
    name.append(element('i'), document.createTextNode(source.label));
    item.append(name, element('div', 'source-date', `${formatDate(source.modified_at)} · ${source.age_days} 天`));
    return item;
  });
  ribbon.replaceChildren(intro, ...items);
}

function renderPortfolio(snapshot) {
  dashboardState.records.clear();
  const grid = document.getElementById('portfolioGrid');
  grid.className = 'portfolio-grid live-data';
  const corner = element('div', 'matrix-head matrix-corner', '领域 × 状态');
  const headers = portfolioBuckets.map(bucket => element('div', `matrix-head matrix-status ${bucket.tone}`.trim(), bucket.label));
  const children = [corner, ...headers];
  const domains = Object.keys(domainDescriptions);
  const projects = snapshot.projects || [];
  for (const domain of domains) {
    const domainCell = element('div', 'domain-cell');
    domainCell.append(element('strong', '', domain), element('span', '', domainDescriptions[domain]));
    children.push(domainCell);
    for (const bucket of portfolioBuckets) {
      const cell = element('div', 'matrix-cell');
      let members = projects.filter(project => project.domain === domain && project.bucket === bucket.key);
      if (bucket.key === '新信号' && domain === '其他项目') {
        for (const emerging of snapshot.emerging_projects || []) cell.append(createEmergingNode(emerging));
      }
      const tone = bucket.key === '等待判断'
        ? 'state-wait'
        : bucket.key === '待核实 / 停滞'
          ? 'state-verify'
          : bucket.key === '阶段成果'
            ? 'state-complete'
            : '';
      for (const project of members) cell.append(createProjectNode(project, tone));
      if (!cell.children.length) cell.append(element('div', 'matrix-empty', '—'));
      children.push(cell);
    }
  }

  const archiveProjects = projects.filter(project => project.bucket === '非当前项目');
  const archiveDomain = element('div', 'domain-cell last-row');
  archiveDomain.append(element('strong', '', '参考 / 历史'), element('span', '', '保留来源，不占用当前推进容量'));
  const archiveCell = element('div', 'matrix-cell archive-cell last-row');
  for (const project of archiveProjects) archiveCell.append(createProjectNode(project, 'state-archive'));
  if (!archiveProjects.length) archiveCell.append(element('div', 'matrix-empty', '无非当前项目'));
  children.push(archiveDomain, archiveCell);
  grid.replaceChildren(...children);
  const archived = snapshot.archived_projects || [];
  document.getElementById('archiveCaption').textContent = `已暂停 / 已结束项目 · ${archived.length}`;
  for (const [state, id, label] of [['paused', 'pausedProjects', '已暂停'], ['ended', 'endedProjects', '已结束']]) {
    const list = document.getElementById(id);
    const members = archived.filter(p => p.lifecycle.state === state);
    list.replaceChildren(element('h3', '', `${label} · ${members.length}`),
      ...members.map(p => createProjectNode(p, 'state-archive')));
  }

  document.getElementById('emptySearch').classList.remove('show');
}

function createRailButton(record, typeLabel, dateLabel, decision = false) {
  const key = registerRecord(record);
  const button = element('button', 'rail-item rail-button');
  button.type = 'button';
  button.dataset.recordKey = key;
  button.dataset.search = `${record.title} ${record.state} ${record.summary} ${record.next}`.toLowerCase();
  button.append(element('span', 'rail-type', typeLabel));
  const copy = element('div', 'rail-copy');
  copy.append(element('strong', '', record.title), element('span', '', record.brief?.work_cycle?.suggestion ? `${record.brief.work_cycle.suggestion.label}：${record.brief.work_cycle.suggestion.next_step}` : record.brief ? record.summary : record.next || record.summary));
  if (record.brief) copy.append(element('span', 'brief-entry', '查看建议 / 继续工作 →'));
  button.append(copy, element('span', 'rail-date', dateLabel));
  if (decision) button.classList.add('decision-item');
  button.addEventListener('click', () => openDrawer(key, button));
  return button;
}

function renderRails(snapshot) {
  function activityRecord(task) {
    const target = task.source_target || {};
    return {title: task.task, state: task.current_brief ? `项目：${task.current_brief.project_state} · 最新任务：${task.current_brief.task_state || '未确认'}` : task.status,
      summary: task.progress,
      next: task.work_cycle?.suggestion?.next_step || task.current_brief?.work_cycle?.suggestion?.next_step || task.current_brief?.next_action || task.progress,
      brief: task.current_brief,
      evidence: `${task.discovery_reason || ''}\n${task.activity_evidence?.map(item => `${item.kind === 'formal' ? '正式记录' : '会话活动'} · ${item.tool} · ${formatDate(item.updated_at, true)} · ${item.assignment}`).join('\n') || ''}\n活动不等于正式验收或业务优先级。`,
      source: target.path || task.evidence, uri: target.uri || ''};
  }
  const discovery = snapshot.activity_discovery || {};
  const discovered = snapshot.discovered_projects || [];
  const activeCount = discovered.filter(task => task.active_candidate !== false).length;
  document.getElementById('discoveryCaption').textContent = `${activeCount} 项活动线索 · ${discovered.length - activeCount} 项近期交付 · 点击查看依据`;
  document.getElementById('discoveredProjectList').replaceChildren(...discovered.map(task =>
    createRailButton(activityRecord(task), task.active_candidate === false ? '近期交付' : task.new_project ? '新工作' : task.diagnostic_signal ? '近期排错' : '自动发现', formatDate(task.updated_at))));
  if (!discovered.length) document.getElementById('discoveredProjectList').append(element('p', '', '窗口内未发现新的项目证据。'));
  const review = [...(discovery.review || []), ...(discovery.warnings || []).map(item => ({title: '采集投影待检查', ...item}))];
  document.getElementById('discoveryReviewList').replaceChildren(...review.map(item => element('p', '', `${item.title}：${item.reason}`)));
  if (!review.length) document.getElementById('discoveryReviewList').append(element('p', '', '当前未发现归属冲突或损坏的采集投影。'));
  const focus = snapshot.recent_focus || [];
  document.getElementById('recentFocusList').replaceChildren(...focus.map(task => {
    const record = activityRecord(task);
    return createRailButton(record, '确认重点', task.current_brief?.recorded_at ? formatDate(task.current_brief.recorded_at) : task.updated_at ? formatDate(task.updated_at) : '待更新');
  }));
  const completed = snapshot.recently_completed_projects || [];
  document.getElementById('completedCaption').textContent = `${completed.length} 项 · 全部展示`;
  document.getElementById('completedList').replaceChildren(
    ...completed.map(project => createRailButton(recordForProject(project), '阶段成果', project.latest_evidence_date || '待核')),
  );

  const ledgers = snapshot.task_ledgers || [];
  const taskRegister = snapshot.task_register || [];
  const ledgerSummary = snapshot.task_ledger_summary || {};
  const registerLedger = {
    title: '正式任务登记表',
    total: taskRegister.length,
    completed: ledgerSummary.formal_completed || 0,
    deferred: ledgerSummary.formal_deferred || 0,
    open: ledgerSummary.formal_open || 0,
    needs_review: 0,
    conserved: true,
    source_target: taskRegister[0]?.source_target || {},
  };
  document.getElementById('ledgerCaption').textContent = `${taskRegister.length} 条正式任务 · ${ledgerSummary.total || 0} 个结构化范围项`;
  document.getElementById('ledgerList').replaceChildren(
    ...[registerLedger, ...ledgers].map(ledger => createRailButton(
      recordForLedger(ledger),
      ledger.conserved ? '守恒通过' : '总账异常',
      `${ledger.completed || 0}/${ledger.total || 0}`,
    )),
  );

  const decisions = snapshot.decision_entries || [];
  const confirmations = snapshot.confirmation_queue || [];
  document.getElementById('confirmationCaption').textContent = `${confirmations.length} 条 · 正式 ${decisions.length} · 防漏 ${snapshot.omission_findings?.length || 0}`;
  document.getElementById('confirmationList').replaceChildren(
    ...confirmations.map(entry => createRailButton(
      recordForConfirmation(entry),
      entry.kind || '待确认',
      entry.priority || entry.date || '待核',
      true,
    )),
  );
}

function maturityStage(maturity) {
  if (String(maturity).includes('🟢')) return { className: 'stage-3', label: '已实践' };
  if (String(maturity).includes('🟡')) return { className: 'stage-2', label: '发展中' };
  return { className: 'stage-1', label: '待补证' };
}

function renderMethods(snapshot) {
  const panel = document.querySelector('.method-space');
  const head = element('div', 'panel-head');
  head.append(element('h3', '', '方法论证据管线'), element('span', '', `${snapshot.capabilities?.length || 0} 个能力域 · 来自正式能力地图`));
  const stageHead = element('div', 'stage-head');
  ['知识资产', '候选', '已提炼', '已实践', '已复验', '可复用'].forEach(label => stageHead.append(element('div', '', label)));
  const rows = (snapshot.capabilities || []).map(capability => {
    const row = element('div', 'method-row');
    row.dataset.search = `${capability.domain} ${capability.judgement}`.toLowerCase();
    const label = element('div', 'method-label');
    label.append(element('strong', '', capability.domain), element('span', '', capability.judgement));
    const stage = maturityStage(capability.maturity);
    const stageCell = element('div', `stage-cell ${stage.className}`);
    stageCell.append(element('span', 'method-chip', stage.label));
    row.append(label, stageCell);
    return row;
  });
  const rule = element('div', 'method-rule');
  const p0 = (snapshot.capability_gaps || []).filter(gap => gap.priority.includes('P0')).map(gap => gap.capability);
  rule.append(element('b', '', '能力闸门'), element('span', '', p0.length ? `P0 待补：${p0.join('、')}。成熟度只按证据阶段表达。` : '能力成熟度只按证据阶段表达。'));
  panel.replaceChildren(head, stageHead, ...rows, rule);
}

function renderEvidence(snapshot) {
  const panel = document.querySelector('.evidence-space');
  const head = element('div', 'panel-head');
  head.append(element('h3', '', '证据与建议'), element('span', '', `${snapshot.recommendations?.length || 0} 条 · 保留依据与停止条件`));
  const list = element('div', 'evidence-list');
  for (const recommendation of snapshot.recommendations || []) {
    const tone = recommendation.type === '推断' ? ' infer' : recommendation.type === '事实驱动' ? '' : ' action';
    const item = element('div', `evidence-item${tone}`);
    item.append(element('span', 'evidence-type', recommendation.type));
    const copy = element('div');
    copy.append(
      element('div', 'evidence-date', `${recommendation.priority} · ${recommendation.stop_condition || '持续观察'}`),
      element('div', 'evidence-title', recommendation.recommendation),
      element('div', 'evidence-note', `${recommendation.basis} 下一步：${recommendation.next_action}`),
    );
    item.append(copy);
    list.append(item);
  }
  panel.replaceChildren(head, list);
}

function openDrawer(key, trigger) {
  const record = dashboardState.records.get(key);
  if (!record) return;
  dashboardState.lastFocused = trigger || document.activeElement;
  document.getElementById('drawerTitle').textContent = record.title;
  document.getElementById('drawerState').textContent = record.state;
  document.getElementById('drawerSummary').textContent = record.summary;
  document.getElementById('drawerNext').textContent = record.next;
  document.getElementById('drawerNext').parentElement.hidden=!!record.brief?.work_cycle?.suggestion;
  document.getElementById('drawerEvidence').textContent = record.evidence;
  document.getElementById('drawerSource').textContent = record.source;
  const openSource = document.getElementById('drawerOpenSource');
  openSource.hidden = !record.uri;
  openSource.href = record.uri || '#';
  renderBrief(record.brief);
  document.getElementById('drawerBackdrop').classList.add('open');
  document.getElementById('drawerBackdrop').setAttribute('aria-hidden', 'false');
  document.getElementById('drawerClose').focus();
}

function renderBrief(brief) {
  dashboardState.activeBrief = brief || null;
  renderLifecycle(brief);
  window.workCycle?.renderProject(brief);
  const panel = document.getElementById('projectBrief');
  panel.hidden = !brief;
  panel.replaceChildren();
  const preview = document.getElementById('continuationPreview');
  preview.hidden = true;
  document.getElementById('continuationText').value = '';
  document.getElementById('continuationStatus').textContent = '';
  document.getElementById('continueWork').hidden = !brief || (brief.lifecycle && brief.lifecycle.state !== 'active');
  if (!brief) return;
  const fields = [
    ['项目状态 · 任务状态', `${brief.project_state} · ${brief.task_state || '未确认'}（各自独立）`],
    ['目标 / 主线（项目页原文）', brief.goal],
    ['最新可追溯任务', `${brief.task || '未确认'}\n${brief.recorded_at ? formatDate(brief.recorded_at, true) : '未找到正式记录'} · ${brief.basis}`],
    ['本次未完成', `${brief.remaining}\n${brief.remaining_kind || ''}`],
    ['接续边界', [brief.notice, ...(brief.boundaries || [])].join('\n')],
  ];
  for (const [label, value] of fields) {
    const section = element('div', 'brief-field');
    section.append(element('strong', '', label), element('p', '', value));
    panel.append(section);
  }
  if (brief.activity) {
    const section = element('div', 'brief-field brief-unverified');
    section.append(element('strong', '', '未确认的会话线索'),
      element('p', '', `${formatDate(brief.activity.date, true)} · ${brief.activity.text}`),
      element('small', '', '未覆盖正式状态；接续前核对。'));
    panel.append(section);
  }
  const artifacts = element('div', 'brief-field');
  artifacts.append(element('strong', '', '最新任务关联文件'));
  for (const item of brief.artifacts || []) {
    const row = element('div', 'brief-artifact');
    row.append(element('span', '', `${item.label} · ${item.exists ? '存在' : '未找到'}`));
    const path = element('input', 'brief-path');
    path.readOnly = true;
    path.value = item.path;
    path.setAttribute('aria-label', `${item.label} 路径`);
    row.append(path);
    if (item.exists && item.uri?.startsWith('obsidian://open?')) {
      const link = element('a', '', '打开原文 ↗');
      link.href = item.uri;
      row.append(link);
    }
    artifacts.append(row);
  }
  if (!brief.artifacts?.length) artifacts.append(element('p', '', '未记录可定位的成果文件；不能推断没有成果。'));
  panel.append(artifacts);
  const provenance = element('details', 'brief-sources');
  provenance.append(element('summary', '', '来源与最近任务'));
  for (const source of brief.sources || []) {
    provenance.append(element('p', '', `${source.label}\n${source.path}${source.line ? ` · 第 ${source.line} 行` : ''}`));
  }
  for (const task of brief.recent_tasks || []) {
    provenance.append(element('p', '', `${formatDate(task.date)} · ${task.task} · ${task.state}`));
  }
  panel.append(provenance);
}

async function previewContinuation() {
  const brief = dashboardState.activeBrief;
  if (!brief) return;
  document.getElementById('continuationPreview').hidden = false;
  const text = document.getElementById('continuationText');
  text.value = '正在核对当前版本与本人决定…';
  try { text.value = await window.workCycle.packet(brief); }
  catch (error) { text.value = ''; document.getElementById('continuationStatus').textContent = error.message; }
  text.focus();
  text.scrollIntoView({ block: 'nearest' });
}

function renderLifecycle(brief) {
  const lifecycle = brief?.lifecycle;
  document.getElementById('lifecycleActions').hidden = !lifecycle?.project_key;
  const state = lifecycle?.state || 'active';
  document.getElementById('pauseProject').hidden = state !== 'active';
  document.getElementById('endProject').hidden = state === 'ended';
  document.getElementById('resumeProject').hidden = state === 'active';
  document.getElementById('lifecycleStatus').textContent = '';
}

async function changeProjectState(state) {
  const brief = dashboardState.activeBrief;
  if (!brief?.lifecycle?.project_key || dashboardState.lifecycleBusy) return;
  const status = document.getElementById('lifecycleStatus');
  const buttons = [...document.querySelectorAll('.lifecycle-buttons button')];
  dashboardState.lifecycleBusy = true;
  buttons.forEach(b => { b.disabled = true; });
  status.textContent = '正在保存项目决定…';
  try {
    const session = await fetch('/api/project-lifecycle', { cache: 'no-store' });
    if (!session.ok) throw new Error('请从更新后的本地工作台打开，当前服务不支持项目管理。');
    const { token } = await session.json();
    const response = await fetch('/api/project-lifecycle', {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Workbench-Token': token },
      body: JSON.stringify({ project_key: brief.lifecycle.project_key, revision: brief.lifecycle.revision, state }),
    });
    const result = await response.json();
    if (!response.ok || !result.ok) throw new Error(result.error || '保存未成功，请刷新后重试。');
    // Server returns only after rebuilding the persisted snapshot.
    render(result.snapshot);
    const project = [...result.snapshot.projects, ...result.snapshot.recent_focus, ...result.snapshot.discovered_projects, ...result.snapshot.archived_projects]
      .find(p => p.lifecycle?.project_key === brief.lifecycle.project_key && p.current_brief);
    if (project && dashboardState.activeBrief?.lifecycle?.project_key === brief.lifecycle.project_key) {
      renderBrief(project.current_brief);
      const record = recordForProject(project);
      document.getElementById('drawerState').textContent = record.state;
      document.getElementById('drawerNext').textContent = record.next;
  document.getElementById('drawerNext').parentElement.hidden=!!record.brief?.work_cycle?.suggestion;
    }
    if (dashboardState.activeBrief?.lifecycle?.project_key === brief.lifecycle.project_key) status.textContent = state === 'active' ? '已恢复跟进，可准备接续包交给 AI。' : state === 'paused'
      ? '已暂停，已移至下方“已暂停 / 已结束项目”。需要时可恢复跟进。'
      : '已结束并归档，已移出当前看板。记录与成果完整保留，可随时恢复跟进。';
  } catch (error) {
    status.textContent = String(error.message || error);
  } finally {
    dashboardState.lifecycleBusy = false;
    buttons.forEach(b => { b.disabled = false; });
  }
}

async function copyContinuation() {
  const text = document.getElementById('continuationText');
  const status = document.getElementById('continuationStatus');
  try {
    await navigator.clipboard.writeText(text.value);
    status.textContent = '已复制。可粘贴到现有 AI 对话，并补充本次具体要求。';
  } catch {
    text.focus();
    text.select();
    status.textContent = '浏览器未允许自动复制；内容已选中，请按 Ctrl+C 复制。';
  }
}

function downloadContinuation() {
  const brief = dashboardState.activeBrief;
  if (!brief) return;
  const url = URL.createObjectURL(new Blob([document.getElementById('continuationText').value], { type: 'text/markdown;charset=utf-8' }));
  const link = element('a');
  link.href = url;
  link.download = `${brief.project.replace(/[\\/:*?"<>|]/g, '_')}-接续包.md`;
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  document.getElementById('continuationStatus').textContent = '已生成下载文件；未发送到任何 AI 服务。';
}

function closeDrawer() {
  const backdrop = document.getElementById('drawerBackdrop');
  backdrop.classList.remove('open');
  backdrop.setAttribute('aria-hidden', 'true');
  dashboardState.lastFocused?.focus();
}

function filterDashboard() {
  const query = document.getElementById('searchInput').value.trim().toLowerCase();
  const searchable = document.querySelectorAll('[data-search]');
  let visible = 0;
  searchable.forEach(node => {
    const match = !query || node.dataset.search.includes(query);
    node.hidden = !match;
    if (match) visible += 1;
  });
  document.getElementById('emptySearch').classList.toggle('show', visible === 0);
}

function render(snapshot) {
  dashboardState.snapshot = snapshot;
  renderDirective(snapshot);
  renderStatusOverview(snapshot);
  renderSources(snapshot);
  renderPortfolio(snapshot);
  renderRails(snapshot);
  renderMethods(snapshot);
  renderEvidence(snapshot);
  window.workCycle?.render(snapshot);
  document.getElementById('footerFreshness').textContent = `快照 ${formatDate(snapshot.generated_at, true)} · ${snapshot.projects.length} 个当前项目 · ${snapshot.archived_projects?.length || 0} 个暂停或结束项目 · 项目决定由本人操作保存`;
  if (document.getElementById('searchInput').value.trim()) filterDashboard();
}

function renderError(error) {
  document.getElementById('directiveTitle').textContent = '正式事实快照读取失败';
  document.getElementById('directiveSummary').textContent = String(error);
  document.querySelectorAll('.status-count').forEach(node => { node.textContent = '—'; });
  document.getElementById('decisionFact').textContent = '无法对账';
  document.getElementById('directiveInference').textContent = '不展示静态替代数据';
  const grid = document.getElementById('portfolioGrid');
  grid.className = '';
  grid.replaceChildren(element('div', 'live-load-error', '页面不会用静态演示数据替代真实项目。请保持桌面工作台运行后刷新。'));
}

async function loadSnapshot() {
  try {
    const response = await fetch(`../data/operations_snapshot.json?ts=${Date.now()}`, { cache: 'no-store' });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    render(await response.json());
  } catch (error) {
    renderError(error);
  }
}

document.getElementById('drawerClose').addEventListener('click', closeDrawer);
document.getElementById('continueWork').addEventListener('click', previewContinuation);
document.getElementById('pauseProject').addEventListener('click', () => changeProjectState('paused'));
document.getElementById('endProject').addEventListener('click', () => changeProjectState('ended'));
document.getElementById('resumeProject').addEventListener('click', () => changeProjectState('active'));
document.getElementById('copyContinuation').addEventListener('click', copyContinuation);
document.getElementById('downloadContinuation').addEventListener('click', downloadContinuation);
document.getElementById('drawerBackdrop').addEventListener('click', event => {
  if (event.target === event.currentTarget) closeDrawer();
});
document.getElementById('searchInput').addEventListener('input', filterDashboard);
document.addEventListener('keydown', event => {
  if (event.key === 'Escape') closeDrawer();
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
    event.preventDefault();
    document.getElementById('searchInput').focus();
  }
});
document.querySelectorAll('.nav button').forEach(button => button.addEventListener('click', () => {
  document.querySelectorAll('.nav button').forEach(item => item.classList.remove('active'));
  button.classList.add('active');
  document.getElementById(button.dataset.target)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
}));
document.getElementById('focusAction').addEventListener('click', () => {
  const decision = document.querySelector('.decision-item');
  decision?.scrollIntoView({ behavior: 'smooth', block: 'center' });
  window.setTimeout(() => decision?.focus({ preventScroll: true }), 420);
});

updateClock();
window.setInterval(updateClock, 1000);
window.setInterval(loadSnapshot, 15000);
loadSnapshot();
