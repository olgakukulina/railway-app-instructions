import {
  AlignmentType,
  Document,
  Footer,
  Packer,
  PageNumber,
  Paragraph,
  TextRun,
} from 'docx'
import html2canvas from 'html2canvas'
import { jsPDF } from 'jspdf'

// Инструкции приходят как plain-text "Заголовок раздела\n\nТекст раздела\n\n..."
// (см. TaskServiceImpl.readContentFromGeneratedJson на бэкенде), иногда с остатками
// Markdown из LLM (**bold**, # heading). Ниже — тот же разбор, что и в серверном
// assembler-service/docx_generator_v2.py, только на клиенте и для DOCX/PDF сразу.
const MD_HEADING_RE = /^\s{0,3}(#{1,6})\s+(.*)$/
const MD_BOLD_ONLY_RE = /^\*\*(.+)\*\*$/
const MD_BOLD_RE = /\*\*(.+?)\*\*/
const MD_ITALIC_RE = /(?<!\*)\*([^*\n]+)\*(?!\*)/

const TITLE_LINES = [
  'ИНСТРУКЦИЯ',
  'о порядке обслуживания и организации движения',
  'на железнодорожном пути необщего пользования',
]

function safeFileName(value, extension) {
  const normalized = String(value || 'Инструкция')
    .replace(/[<>:"/\\|?*\u0000-\u001F]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, 120)

  return `${normalized || 'Инструкция'}.${extension}`
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

function buildSubjectLine(station, organization) {
  const stationPart = `примыкающем к железнодорожной станции ${station || 'не указана'}`
  return organization ? `${organization}, ${stationPart}` : stationPart
}

// Разбивает текст инструкции на блоки: заголовок раздела, markdown-подзаголовок
// или обычный абзац (возможно многострочный).
function parseContentBlocks(content) {
  const normalized = String(content || '')
    .replace(/\r\n/g, '\n')
    .replace(/\r/g, '\n')

  return normalized
    .split(/\n{2,}/)
    .map((block) => block.trim())
    .filter(Boolean)
    .map(classifyBlock)
}

function classifyBlock(block) {
  const lines = block
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)

  if (lines.length === 1) {
    const line = lines[0]

    const heading = line.match(MD_HEADING_RE)
    if (heading) {
      return { type: 'sub-heading', text: stripMarkdown(heading[2]) }
    }

    const boldOnly = line.match(MD_BOLD_ONLY_RE)
    if (boldOnly) {
      return { type: 'sub-heading', text: stripMarkdown(boldOnly[1]) }
    }

    const looksLikeSectionTitle =
      line.length > 0 &&
      line.length <= 140 &&
      !/[.!?;:,]$/.test(line) &&
      !line.includes('**')
    if (looksLikeSectionTitle) {
      return { type: 'section-heading', text: line }
    }
  }

  return { type: 'paragraph', lines }
}

function stripMarkdown(text) {
  return text.replace(/\*\*/g, '').trim()
}

// Разбирает строку на runs с учётом **bold** / *italic*, маркеры в вывод не попадают.
function buildInlineRuns(text) {
  const runs = []
  let rest = text

  while (rest.length) {
    const match = rest.match(MD_BOLD_RE)
    if (!match) {
      pushItalicRuns(rest, runs)
      break
    }
    if (match.index > 0) pushItalicRuns(rest.slice(0, match.index), runs)
    runs.push({ text: match[1], bold: true })
    rest = rest.slice(match.index + match[0].length)
  }

  return runs.length ? runs : [{ text }]
}

function pushItalicRuns(text, runs) {
  if (!text) return
  let rest = text

  while (rest.length) {
    const match = rest.match(MD_ITALIC_RE)
    if (!match) {
      runs.push({ text: rest })
      break
    }
    if (match.index > 0) runs.push({ text: rest.slice(0, match.index) })
    runs.push({ text: match[1], italic: true })
    rest = rest.slice(match.index + match[0].length)
  }
}

// ---------------------------------------------------------------------------
// DOCX
// ---------------------------------------------------------------------------

const TWIPS_PER_CM = 567
const cm = (value) => Math.round(value * TWIPS_PER_CM)

function buildDocxTitleParagraphs(station, organization) {
  const paragraphs = TITLE_LINES.map((line, index) =>
    new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { before: index === 0 ? 1200 : 0, after: 80 },
      children: [new TextRun({ text: line, bold: true, size: 32 })],
    }),
  )

  paragraphs.push(
    new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { before: 300, after: 300 },
      children: [new TextRun({ text: buildSubjectLine(station, organization), bold: true, size: 32 })],
    }),
  )

  paragraphs.push(
    new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { before: 3200 },
      children: [new TextRun({ text: `${new Date().getFullYear()} г.`, bold: true, size: 28 })],
    }),
  )

  return paragraphs
}

function buildDocxBodyParagraphs(blocks) {
  const paragraphs = []
  let sectionNumber = 0

  blocks.forEach((block) => {
    if (block.type === 'section-heading') {
      sectionNumber += 1
      paragraphs.push(
        new Paragraph({
          alignment: AlignmentType.CENTER,
          pageBreakBefore: sectionNumber === 1,
          keepNext: true,
          spacing: { before: 360, after: 200, line: 360, lineRule: 'exact' },
          children: [
            new TextRun({
              text: `РАЗДЕЛ ${sectionNumber}.   ${block.text.toUpperCase()}`,
              bold: true,
              size: 28,
            }),
          ],
        }),
      )
      return
    }

    if (block.type === 'sub-heading') {
      paragraphs.push(
        new Paragraph({
          keepNext: true,
          spacing: { before: 200, after: 120, line: 360, lineRule: 'exact' },
          children: [new TextRun({ text: block.text, bold: true, size: 28 })],
        }),
      )
      return
    }

    block.lines.forEach((line) => {
      paragraphs.push(
        new Paragraph({
          alignment: AlignmentType.JUSTIFIED,
          indent: { firstLine: cm(1.25) },
          spacing: { after: 120, line: 360, lineRule: 'exact' },
          children: buildInlineRuns(line).map(
            (run) =>
              new TextRun({ text: run.text, bold: Boolean(run.bold), italics: Boolean(run.italic), size: 28 }),
          ),
        }),
      )
    })
  })

  return paragraphs
}

export async function exportInstructionDocx({ content, title, station, organization }) {
  const blocks = parseContentBlocks(content)

  const footer = new Footer({
    children: [
      new Paragraph({
        alignment: AlignmentType.RIGHT,
        children: [new TextRun({ children: [PageNumber.CURRENT], size: 20, color: '808080' })],
      }),
    ],
  })

  const document = new Document({
    styles: {
      default: {
        document: {
          run: { font: 'Times New Roman', size: 28 },
        },
      },
    },
    sections: [
      {
        properties: {
          page: {
            margin: { top: cm(2), bottom: cm(2), left: cm(2.5), right: cm(1.5) },
          },
        },
        footers: { default: footer },
        children: [...buildDocxTitleParagraphs(station, organization), ...buildDocxBodyParagraphs(blocks)],
      },
    ],
  })

  const blob = await Packer.toBlob(document)
  triggerBlobDownload(blob, safeFileName(`${title} — ${station}`, 'docx'))
}

// ---------------------------------------------------------------------------
// PDF
// ---------------------------------------------------------------------------

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
}

function renderInlineHtml(line) {
  return buildInlineRuns(line)
    .map((run) => {
      const escaped = escapeHtml(run.text)
      if (run.bold) return `<strong>${escaped}</strong>`
      if (run.italic) return `<em>${escaped}</em>`
      return escaped
    })
    .join('')
}

function buildPdfHtml(content, station, organization) {
  const blocks = parseContentBlocks(content)
  const parts = []

  parts.push('<div class="pdf-title-block">')
  TITLE_LINES.forEach((line) => {
    parts.push(`<p class="pdf-title-line">${escapeHtml(line)}</p>`)
  })
  parts.push(`<p class="pdf-title-subject">${escapeHtml(buildSubjectLine(station, organization))}</p>`)
  parts.push('</div>')
  parts.push('<hr class="pdf-title-rule" />')

  let sectionNumber = 0
  blocks.forEach((block) => {
    if (block.type === 'section-heading') {
      sectionNumber += 1
      parts.push(
        `<p class="pdf-section-heading">РАЗДЕЛ ${sectionNumber}.&nbsp;&nbsp;&nbsp;${escapeHtml(
          block.text.toUpperCase(),
        )}</p>`,
      )
      return
    }

    if (block.type === 'sub-heading') {
      parts.push(`<p class="pdf-sub-heading">${escapeHtml(block.text)}</p>`)
      return
    }

    block.lines.forEach((line) => {
      parts.push(`<p class="pdf-paragraph">${renderInlineHtml(line)}</p>`)
    })
  })

  return parts.join('\n')
}

export async function exportInstructionPdf({ content, title, station, organization }) {
  const exportElement = document.createElement('article')
  exportElement.className = 'pdf-export-document'
  exportElement.innerHTML = buildPdfHtml(content, station, organization)
  document.body.appendChild(exportElement)

  try {
    if (document.fonts?.ready) await document.fonts.ready

    const canvas = await html2canvas(exportElement, {
      scale: 2,
      useCORS: true,
      backgroundColor: '#ffffff',
      logging: false,
      windowWidth: 1000,
    })

    const pdf = new jsPDF({ orientation: 'portrait', unit: 'mm', format: 'a4' })
    const pageWidth = pdf.internal.pageSize.getWidth()
    const pageHeight = pdf.internal.pageSize.getHeight()
    const margin = 18
    const footerSpace = 8
    const printableWidth = pageWidth - margin * 2
    const printableHeight = pageHeight - margin * 2 - footerSpace
    const imageWidth = printableWidth
    const imageHeight = (canvas.height * imageWidth) / canvas.width
    const imageData = canvas.toDataURL('image/jpeg', 0.96)
    const totalPages = Math.max(1, Math.ceil(imageHeight / printableHeight))

    let remainingHeight = imageHeight
    let imagePosition = margin
    let pageNumber = 1

    const addPageNumber = () => {
      pdf.setFont('helvetica', 'normal')
      pdf.setFontSize(9)
      pdf.setTextColor(120, 120, 120)
      pdf.text(`${pageNumber} / ${totalPages}`, pageWidth - margin, pageHeight - margin / 2, { align: 'right' })
    }

    pdf.addImage(imageData, 'JPEG', margin, imagePosition, imageWidth, imageHeight, undefined, 'FAST')
    addPageNumber()
    remainingHeight -= printableHeight

    while (remainingHeight > 0) {
      pdf.addPage()
      pageNumber += 1
      imagePosition = margin - (imageHeight - remainingHeight)
      pdf.addImage(imageData, 'JPEG', margin, imagePosition, imageWidth, imageHeight, undefined, 'FAST')
      addPageNumber()
      remainingHeight -= printableHeight
    }

    pdf.save(safeFileName(`${title} — ${station}`, 'pdf'))
  } finally {
    exportElement.remove()
  }
}
