export interface StatusInfo {
  text: string
  tagColor: string
  hexColor: string
}

export const STATUS_MAP: Record<string, StatusInfo> = {
  pending:    { text: '等待中', tagColor: 'default', hexColor: '#aaa' },
  generating: { text: '生成中', tagColor: 'warning', hexColor: '#fa8c16' },
  completed:  { text: '已完成', tagColor: 'success', hexColor: '#52c41a' },
  failed:     { text: '失败',   tagColor: 'danger',  hexColor: '#ff4d4f' },
}
