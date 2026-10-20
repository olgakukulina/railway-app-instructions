import {
  Document,
  HeadingLevel,
  Packer,
  Paragraph,
  ShadingType,
  Table,
  TableCell,
  TableLayoutType,
  TableRow,
  TextRun,
  WidthType,
} from 'docx'
import html2canvas from 'html2canvas'
import { jsPDF } from 'jspdf'

function safeFileName(value, extension) {
  const normalized = String(value || 'Инструкция')
    .replace(/[<>:"/\\|?*\u0000-\u001F]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, 120)

  return `${normalized || 'Инструкция'}.${extension}`
}

// Выравнивает число колонок и отбрасывает пустые строки/таблицы.
// Без tables (старые задачи) — пустой список, экспорт как раньше.
export function normalizeTables(tables) {
  if (!Array.isArray(tables)) return []
  const toCells = (row) => (Array.isArray(row) ? row.map((cell) => (cell == null ? '' : String(cell))) : [])

  return tables
    .map((table) => {
      let headers = toCells(table?.headers)
      if (!headers.some((cell) => cell.trim())) headers = []
      const rows = (Array.isArray(table?.rows) ? table.rows : [])
        .map(toCells)
        .filter((row) => row.some((cell) => cell.trim()))
      const columns = Math.max(headers.length, ...rows.map((row) => row.length))
      const pad = (row) => [...row, ...Array(columns - row.length).fill('')]
      return {
        title: String(table?.title || '').trim(),
        headers: headers.length ? pad(headers) : [],
        rows: rows.map(pad),
      }
    })
    .filter((table) => table.rows.length)
}

function triggerBlobDownload(blob, fileName) {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = fileName
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}

// A4 11906 twips минус поля слева 1134 и справа 850.
const DOCX_TEXT_WIDTH = 11906 - 1134 - 850
const DOCX_HEADER_FILL = 'D9E2F3'

function docxCell(text, width, header, fontSize) {
  return new TableCell({
    width: { size: width, type: WidthType.DXA },
    shading: header ? { fill: DOCX_HEADER_FILL, type: ShadingType.CLEAR, color: 'auto' } : undefined,
    children: [new Paragraph({ children: [new TextRun({ text, bold: header, size: fontSize })] })],
  })
}

function docxTableBlocks(table) {
  const columns = table.rows[0].length
  const columnWidth = Math.floor(DOCX_TEXT_WIDTH / columns)
  const fontSize = columns >= 6 ? 18 : 20
  const rows = []

  if (table.headers.length) {
    rows.push(
      new TableRow({
        tableHeader: true,
        children: table.headers.map((cell) => docxCell(cell, columnWidth, true, fontSize)),
      }),
    )
  }
  table.rows.forEach((row) => {
    rows.push(new TableRow({ children: row.map((cell) => docxCell(cell, columnWidth, false, fontSize)) }))
  })

  return [
    new Paragraph({
      children: [new TextRun({ text: table.title, bold: true, size: 24 })],
      spacing: { before: 240, after: 120 },
      keepNext: true,
    }),
    new Table({
      rows,
      width: { size: columnWidth * columns, type: WidthType.DXA },
      columnWidths: Array(columns).fill(columnWidth),
      layout: TableLayoutType.FIXED,
    }),
  ]
}

export async function exportInstructionDocx({ content, tables, title, station }) {
  const lines = String(content || '').split('\n')

  const paragraphs = lines.map((line) => {
    const trimmed = line.trim()

    if (!trimmed) return new Paragraph({ text: '' })

    if (trimmed.startsWith('РАЗДЕЛ')) {
      return new Paragraph({
        text: trimmed,
        heading: HeadingLevel.HEADING_1,
        spacing: { before: 260, after: 120 },
      })
    }

    if (trimmed === 'ИНСТРУКЦИЯ' || trimmed === 'ПРИЛОЖЕНИЯ') {
      return new Paragraph({
        alignment: 'center',
        children: [new TextRun({ text: trimmed, bold: true, size: 30 })],
        spacing: { before: 240, after: 140 },
      })
    }

    const isApprovalLine = trimmed === 'УТВЕРЖДАЮ'
    return new Paragraph({
      alignment: isApprovalLine ? 'right' : 'left',
      children: [new TextRun({ text: trimmed, bold: isApprovalLine, size: 24 })],
      spacing: { after: 120 },
    })
  })

  const document = new Document({
    sections: [
      {
        properties: {
          page: {
            margin: { top: 1134, right: 850, bottom: 1134, left: 1134 },
          },
        },
        children: [...paragraphs, ...normalizeTables(tables).flatMap(docxTableBlocks)],
      },
    ],
  })

  const blob = await Packer.toBlob(document)
  triggerBlobDownload(blob, safeFileName(`${title} — ${station}`, 'docx'))
}

// Размеры страницы в px совпадают с .pdf-export-document в styles.css.
const PDF_PAGE_WIDTH = 794
const PDF_PAGE_HEIGHT = 1123
const PDF_BODY_HEIGHT = PDF_PAGE_HEIGHT - 70 * 2

function createElement(tag, className, text) {
  const element = document.createElement(tag)
  if (className) element.className = className
  if (text !== undefined) element.textContent = text
  return element
}

// Раскладывает текст и таблицы по страницам скрытого DOM: строки текста и строки
// таблиц добавляются по одной, при переполнении переносятся на новую страницу.
function layoutPdfPages(content, tables) {
  const pages = []
  let body

  const newPage = () => {
    const page = createElement('article', 'pdf-export-document')
    body = createElement('div', 'pdf-page-body')
    page.appendChild(body)
    document.body.appendChild(page)
    pages.push(page)
  }
  const fits = () => body.scrollHeight <= PDF_BODY_HEIGHT

  // Заголовки и пустые строки в конце страницы: переносятся вместе со следующим абзацем.
  let keep = []

  const moveKeepToNewPage = () => {
    const moved = keep.filter((node) => node.textContent.trim())
    keep.forEach((node) => node.remove())
    newPage()
    moved.forEach((node) => body.appendChild(node))
    keep = moved
  }

  // Абзац не влез: на текущую страницу отдаём столько слов, сколько поместится
  // (но не меньше двух строк), остаток — на следующую страницу.
  const splitParagraph = (node, text) => {
    const atPageTop = body.firstChild === node
    const words = text.split(' ')
    let low = 0
    let high = words.length - 1
    while (low < high) {
      const middle = Math.ceil((low + high) / 2)
      node.textContent = words.slice(0, middle).join(' ')
      if (fits()) low = middle
      else high = middle - 1
    }
    node.textContent = words.slice(0, low).join(' ')
    const lineHeight = parseFloat(getComputedStyle(node).lineHeight) || 24

    if (low === 0 || (!atPageTop && node.offsetHeight < 2 * lineHeight - 1)) {
      node.textContent = text
      if (atPageTop) return // одно «слово» выше страницы — порежет снимок
      node.remove()
      if (keep.length && body.firstChild !== keep[0]) moveKeepToNewPage()
      else newPage()
      body.appendChild(node)
      if (!fits()) splitParagraph(node, text)
      return
    }

    const rest = createElement('div', 'pdf-line', words.slice(low).join(' '))
    newPage()
    body.appendChild(rest)
    if (!fits()) splitParagraph(rest, rest.textContent)
  }

  const isHeading = (text) => text.length <= 150 && !/[.;:!?…]$/.test(text)

  const addLine = (line) => {
    const text = line.trim()
    if (!text) {
      if (!body.firstChild) return // пустая строка в начале страницы не нужна
      const blank = createElement('div', 'pdf-line', ' ')
      body.appendChild(blank)
      if (fits()) keep.push(blank)
      else {
        blank.remove()
        newPage()
        keep = []
      }
      return
    }

    const node = createElement('div', 'pdf-line', line)
    body.appendChild(node)
    if (isHeading(text)) {
      if (!fits() && body.firstChild !== node) {
        node.remove()
        moveKeepToNewPage()
        body.appendChild(node)
      }
      keep.push(node)
      return
    }
    if (!fits()) splitParagraph(node, line)
    keep = []
  }

  newPage()
  String(content || '')
    .split('\n')
    .forEach(addLine)

  normalizeTables(tables).forEach((table) => {
    let placed = 0
    let segment

    const startSegment = (continued) => {
      const caption = createElement('div', 'pdf-table-caption', continued ? `${table.title} (продолжение)` : table.title)
      const element = createElement('table', 'pdf-table')
      if (table.headers.length) {
        const headRow = element.createTHead().insertRow()
        table.headers.forEach((cell) => headRow.appendChild(createElement('th', '', cell)))
      }
      segment = { caption, element, tbody: element.createTBody(), rows: 0 }
      body.append(caption, element)
    }

    startSegment(false)
    table.rows.forEach((cells) => {
      const row = createElement('tr')
      cells.forEach((cell) => row.appendChild(createElement('td', '', cell)))
      segment.tbody.appendChild(row)

      // Подпись + шапка + первая строка не влезают даже на пустую страницу — оставляем, порежет снимок.
      const atPageTop = segment.rows === 0 && body.firstChild === segment.caption
      if (!fits() && !atPageTop) {
        row.remove()
        if (segment.rows === 0) {
          segment.caption.remove()
          segment.element.remove()
        }
        newPage()
        startSegment(placed > 0)
        segment.tbody.appendChild(row)
      }
      segment.rows += 1
      placed += 1
    })
  })

  return pages
}

export async function exportInstructionPdf({ content, tables, title, station }) {
  let pages = []

  try {
    if (document.fonts?.ready) await document.fonts.ready
    pages = layoutPdfPages(content, tables)

    const pdf = new jsPDF({ orientation: 'portrait', unit: 'mm', format: 'a4' })
    const pageWidth = pdf.internal.pageSize.getWidth()
    let first = true

    for (const page of pages) {
      const canvas = await html2canvas(page, {
        scale: 2,
        useCORS: true,
        backgroundColor: '#ffffff',
        logging: false,
        windowWidth: 1000,
      })

      // Обычная страница — один кусок; страница с элементом выше A4 режется на несколько.
      const sliceHeight = Math.round((canvas.width * PDF_PAGE_HEIGHT) / PDF_PAGE_WIDTH)
      for (let top = 0; top < canvas.height; top += sliceHeight) {
        const height = Math.min(sliceHeight, canvas.height - top)
        const slice = createElement('canvas')
        slice.width = canvas.width
        slice.height = height
        const context = slice.getContext('2d')
        context.fillStyle = '#ffffff'
        context.fillRect(0, 0, slice.width, slice.height)
        context.drawImage(canvas, 0, top, canvas.width, height, 0, 0, canvas.width, height)

        if (!first) pdf.addPage()
        first = false
        const imageHeight = (height * pageWidth) / canvas.width
        pdf.addImage(slice.toDataURL('image/jpeg', 0.92), 'JPEG', 0, 0, pageWidth, imageHeight, undefined, 'FAST')
      }
    }

    pdf.save(safeFileName(`${title} — ${station}`, 'pdf'))
  } finally {
    pages.forEach((page) => page.remove())
  }
}
