"""Read existing coordination claims; no global configuration or writes."""
def active_claims(content):
    rows=[]; active=False
    for line in content.splitlines():
        if '| 状态' in line and '| 任务' in line:
            active=True
            continue
        if not active:
            continue
        if not line.strip().startswith('|'):
            break
        cells=[cell.strip() for cell in line.strip().strip('|').split('|')]
        if len(cells)>=6 and cells[0]=='进行中' and cells[4] not in ('','-'):
            rows.append(dict(status=cells[0],task=cells[1],agent=cells[2],collab=cells[3],lock=cells[4],evidence=cells[5]))
    return rows
