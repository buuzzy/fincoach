import { useState } from 'react'
import { ActionSheet, Toast, Mask, SpinLoading } from 'antd-mobile'
import { exportReport } from '../../utils/exportUtils'
import './index.css'

interface Props {
  contentRef: React.RefObject<HTMLElement | null>
  filename: string
  onBeforeExport: () => Promise<void>
  onAfterExport: () => void
}

export default function ExportFooter({ contentRef, filename, onBeforeExport, onAfterExport }: Props) {
  const [exporting, setExporting] = useState(false)
  const [sheetVisible, setSheetVisible] = useState(false)

  const handleExport = async (format: 'image' | 'pdf') => {
    setSheetVisible(false)
    setExporting(true)

    try {
      await exportReport(contentRef, format, filename, onBeforeExport, onAfterExport)
      Toast.show({ icon: 'success', content: format === 'image' ? '图片已保存' : 'PDF 已生成' })
    } catch {
      Toast.show({ icon: 'fail', content: '导出失败，请重试' })
    } finally {
      setExporting(false)
    }
  }

  return (
    <>
      <div className="export-footer-bar">
        <button className="export-footer-btn" onClick={() => setSheetVisible(true)}>
          <svg className="export-footer-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
            <polyline points="7 10 12 15 17 10" />
            <line x1="12" y1="15" x2="12" y2="3" />
          </svg>
          导出报告
        </button>
      </div>

      <ActionSheet
        visible={sheetVisible}
        onClose={() => setSheetVisible(false)}
        actions={[
          { text: '保存为图片', key: 'image', onClick: () => handleExport('image') },
          { text: '导出为 PDF', key: 'pdf', onClick: () => handleExport('pdf') },
        ]}
        cancelText="取消"
      />

      <Mask visible={exporting} opacity={0.7}>
        <div className="export-loading-wrap">
          <SpinLoading color="white" style={{ '--size': '36px' }} />
          <span className="export-loading-text">正在生成，请稍候…</span>
        </div>
      </Mask>
    </>
  )
}
