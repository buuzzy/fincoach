import html2canvas from 'html2canvas'
import { jsPDF } from 'jspdf'
import * as echarts from 'echarts'

const EXPORT_OVERLAY_CLASS = 'export-chart-overlay'

/**
 * Before html2canvas capture: convert all ECharts SVG instances
 * inside the container to <img> overlays so html2canvas can
 * render them correctly.
 */
export function prepareChartsForCapture(container: HTMLElement): void {
  const chartDivs = container.querySelectorAll<HTMLElement>('[_echarts_instance_]')
  chartDivs.forEach((div) => {
    const chart = echarts.getInstanceByDom(div)
    if (!chart) return

    const dataURL = chart.getDataURL({ type: 'png', pixelRatio: 2 })
    const img = document.createElement('img')
    img.src = dataURL
    img.className = EXPORT_OVERLAY_CLASS
    Object.assign(img.style, {
      position: 'absolute',
      top: '0',
      left: '0',
      width: '100%',
      height: '100%',
      zIndex: '10',
      pointerEvents: 'none',
    })

    // Overlay inside the chart div itself (not its parent) to avoid
    // covering sibling elements like AI commentary or section titles.
    if (getComputedStyle(div).position === 'static') {
      div.style.position = 'relative'
      div.dataset.exportRelativeAdded = 'true'
    }
    div.appendChild(img)
  })
}

/** Remove all <img> overlays added by prepareChartsForCapture. */
export function restoreChartsAfterCapture(container: HTMLElement): void {
  container.querySelectorAll<HTMLImageElement>(`.${EXPORT_OVERLAY_CLASS}`).forEach((img) => {
    const chartDiv = img.parentElement
    img.remove()
    if (chartDiv?.dataset.exportRelativeAdded) {
      chartDiv.style.position = ''
      delete chartDiv.dataset.exportRelativeAdded
    }
  })
}

/** Capture a DOM element to a canvas via html2canvas. */
export async function captureElement(
  element: HTMLElement,
  options?: Partial<Parameters<typeof html2canvas>[1]>,
): Promise<HTMLCanvasElement> {
  return html2canvas(element, {
    useCORS: true,
    scale: 2,
    backgroundColor: '#ffffff',
    logging: false,
    ...options,
  })
}

/** Download a canvas as a PNG image. */
export function downloadAsImage(canvas: HTMLCanvasElement, filename: string): void {
  canvas.toBlob((blob) => {
    if (!blob) return
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${filename}.png`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  }, 'image/png')
}

/** Download a canvas as a multi-page A4 PDF. */
export function downloadAsPDF(canvas: HTMLCanvasElement, filename: string): void {
  const imgWidth = 190 // A4 content width in mm (210 - 10*2 margins)
  const pageHeight = 277 // A4 content height in mm (297 - 10*2 margins)

  const imgHeight = (canvas.height * imgWidth) / canvas.width
  const pdf = new jsPDF('p', 'mm', 'a4')

  let heightLeft = imgHeight
  let position = 10 // top margin

  const imgData = canvas.toDataURL('image/png')
  pdf.addImage(imgData, 'PNG', 10, position, imgWidth, imgHeight)
  heightLeft -= pageHeight

  while (heightLeft > 0) {
    position = position - pageHeight
    pdf.addPage()
    pdf.addImage(imgData, 'PNG', 10, position, imgWidth, imgHeight)
    heightLeft -= pageHeight
  }

  pdf.save(`${filename}.pdf`)
}

/**
 * Full export pipeline:
 * 1. Call onBefore (set exportMode, wait for re-render)
 * 2. Prepare ECharts overlays
 * 3. Capture to canvas
 * 4. Download as image or PDF
 * 5. Restore DOM, call onAfter
 */
export async function exportReport(
  contentRef: React.RefObject<HTMLElement | null>,
  format: 'image' | 'pdf',
  filename: string,
  onBefore: () => Promise<void>,
  onAfter: () => void,
): Promise<void> {
  const el = contentRef.current
  if (!el) return

  await onBefore()

  // Wait for React re-render + ECharts redraw
  await new Promise((r) => requestAnimationFrame(() => setTimeout(r, 600)))

  try {
    prepareChartsForCapture(el)
    const canvas = await captureElement(el)

    if (format === 'image') {
      downloadAsImage(canvas, filename)
    } else {
      downloadAsPDF(canvas, filename)
    }
  } finally {
    restoreChartsAfterCapture(el)
    onAfter()
  }
}
