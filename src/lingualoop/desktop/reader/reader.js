import { makeBook } from './foliate/view.js'

const identity = new URLSearchParams(location.search).get('document')
const view = document.querySelector('foliate-view')
const codepoints = value => Array.from(value).length
const utf16 = (text, count) => Array.from(text).slice(0, count).join('').length
let bridge, documentInfo, book
let appearance = { dark: false, background: '#F7F3E9', ink: '#3F382F', primary: '#56634F', size: 20 }
let ready = false
let pendingSelection = null
let locationTimer
const font = name => new URL(`../qml/assets/fonts/${name}`, import.meta.url).href

function sourceNodes(doc) {
    return Array.from(doc.querySelectorAll('[data-source-start]'))
}

function sourcePoint(node, offset) {
    const element = (node.nodeType === 1 ? node : node.parentElement)?.closest('[data-source-start]')
    if (!element) return null
    const prefix = node.ownerDocument.createRange()
    prefix.selectNodeContents(element)
    prefix.setEnd(node, offset)
    return Number(element.dataset.sourceStart) + codepoints(prefix.toString())
}

// Native selections can have Element endpoints (select-all, keyboard, accessibility).
function sourceSelection(range) {
    if (range.collapsed) return null
    const doc = range.startContainer.ownerDocument
    const walker = doc.createTreeWalker(doc.body, NodeFilter.SHOW_TEXT)
    const selected = []
    for (let node; (node = walker.nextNode());) {
        if (!node.parentElement.closest('[data-source-start]') || !range.intersectsNode(node)) continue
        if (range.comparePoint(node, node.length) === -1 || range.comparePoint(node, 0) === 1) continue
        const a = node === range.startContainer ? range.startOffset : 0
        const b = node === range.endContainer ? range.endOffset : node.length
        if (a < b) selected.push([sourcePoint(node, a), sourcePoint(node, b)])
    }
    return selected.length ? [selected[0][0], selected.at(-1)[1]] : null
}

function mappedRange(doc, start, end) {
    const nodes = sourceNodes(doc)
    const first = nodes.find(node => Number(node.dataset.sourceEnd) > start)
    const last = nodes.findLast(node => Number(node.dataset.sourceStart) < end)
    if (!first?.firstChild || !last?.firstChild) return null
    const a = Math.max(0, start - Number(first.dataset.sourceStart))
    const b = Math.min(codepoints(last.textContent), end - Number(last.dataset.sourceStart))
    if (b < 0 || first.compareDocumentPosition(last) & Node.DOCUMENT_POSITION_PRECEDING) return null
    const range = doc.createRange()
    range.setStart(first.firstChild, utf16(first.textContent, a))
    range.setEnd(last.firstChild, utf16(last.textContent, b))
    return range
}

function publishSelection(doc, target, allowParagraph) {
    const selection = doc.defaultView.getSelection()
    const range = selection.rangeCount ? sourceSelection(selection.getRangeAt(0)) : null
    if (range) bridge.select(identity, range[0], range[1], 'text')
    else if (allowParagraph && !target.closest('a')) {
        const paragraph = target.closest('p,li,blockquote,h1,h2,h3,h4,h5,h6,pre,td,div')
            || target.closest('[data-source-start]')
        if (!paragraph) return
        const nodes = paragraph.matches('[data-source-start]') ? [paragraph] : sourceNodes(paragraph)
        if (nodes.length) bridge.select(identity, Number(nodes[0].dataset.sourceStart), Number(nodes.at(-1).dataset.sourceEnd), 'paragraph')
    }
}

function installDocument(doc) {
    doc.addEventListener('mouseup', event => {
        if (event.button === 0) setTimeout(() => publishSelection(doc, event.target, true), 0)
    })
    doc.addEventListener('keyup', event => {
        if (event.key === 'Shift' || event.shiftKey || ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'a')) publishSelection(doc, event.target, false)
    })
    doc.addEventListener('keydown', event => {
        if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'f') {
            event.preventDefault()
            // Let QML's application shortcut open its source search popup.
            bridge.find(identity)
        }
    })
    // The display EPUB contains source spans only inside the authorized range.
    for (const element of doc.querySelectorAll('p,div,h1,h2,h3,h4,h5,h6,li,blockquote,figure,table')) {
        if (!element.querySelector('[data-source-start]') && !element.querySelector('img[data-source-image]')) element.remove()
    }
    markBoundary(doc)
}

function setAppearance(value) {
    appearance = { ...appearance, ...value }
    document.documentElement.style.background = appearance.background
    document.documentElement.style.colorScheme = appearance.dark ? 'dark' : 'light'
    document.documentElement.style.scrollbarColor = `${appearance.dark ? '#626A5C' : '#B9B5A9'} ${appearance.background}`
    document.body.style.background = appearance.background
    if (!view.renderer) return
    const family = documentInfo.language === 'japanese' ? 'LinguaJP' : documentInfo.language === 'english' ? 'Georgia' : 'LinguaSC'
    view.renderer.setStyles(`
        @font-face { font-family: LinguaSC; src: url('${font('NotoSerifSC-Regular.otf')}'); }
        @font-face { font-family: LinguaJP; src: url('${font('NotoSerifJP-Regular.otf')}'); }
        :root { color-scheme: ${appearance.dark ? 'dark' : 'light'}; background: ${appearance.background}; color: ${appearance.ink}; }
        body { font-family: ${family}, serif; font-size: ${appearance.size}px; line-height: 1.85; padding: 20px 0 56px; overflow-wrap: break-word; }
        p { margin: 0 0 .9em; } h1,h2,h3 { font-weight: 500; line-height: 1.4; margin: 1.1em 0 .9em; }
        h1 { font-size: 1.55em; } h2 { font-size: 1.3em; } h3 { font-size: 1.12em; }
        body > :first-child { margin-top: 0; } img { max-width: 100%; height: auto; }
        table { max-width: 100%; border-collapse: collapse; } td,th { padding: .35em; }
        pre { white-space: pre-wrap; } a { color: ${appearance.primary}; } rt,rp { user-select: none; }
        ::selection { background: ${appearance.dark ? '#56634F' : '#DCE4D2'}; color: ${appearance.ink}; }
        [data-reader-ui] { position: absolute; right: 8px; border-radius: 4px; padding: 3px 9px; pointer-events: none; user-select: none;
            background: ${appearance.dark ? '#34412F' : '#E1E4D7'}; color: ${appearance.ink}; font: 12px sans-serif; }
    `)
    for (const {doc} of view.renderer.getContents()) requestAnimationFrame(() => markBoundary(doc))
}

function markBoundary(doc) {
    doc.querySelector('[data-reader-ui]')?.remove()
    const end = documentInfo.boundary
    if (!(end > 0)) return
    const range = mappedRange(doc, end - 1, end)
    if (!range || sourcePoint(range.endContainer, range.endOffset) !== end) return
    const marker = doc.createElement('div')
    marker.dataset.readerUi = 'boundary'
    marker.textContent = documentInfo.boundaryLabel
    marker.style.top = `${range.getBoundingClientRect().bottom + doc.documentElement.scrollTop + 4}px`
    doc.body.append(marker)
}

async function showSelection(start, end, select = true) {
    if (!ready) { pendingSelection = [start, end, select]; return }
    const chapter = documentInfo.chapters.find(chapter => chapter.start <= start && start < chapter.end)
        || documentInfo.chapters[0]
    const index = book.sections.findIndex(section => section.id === chapter.href)
    if (index < 0) return
    await view.goTo(index)
    const current = view.renderer.getContents().find(content => content.index === index)
    const range = current && mappedRange(current.doc, start, Math.max(start + 1, end))
    if (range) {
        await view.renderer.goTo({ index, anchor: () => range })
        if (select) {
            const selection = current.doc.defaultView.getSelection()
            selection.removeAllRanges()
            selection.addRange(range)
        }
    }
}

window.linguaReader = {
    view, sourceSelection, mappedRange, setAppearance, showSelection,
    setBoundary(end) { if (documentInfo) { documentInfo.boundary = end; for (const {doc} of view.renderer.getContents()) markBoundary(doc) } },
    get ready() { return ready },
}

new QWebChannel(qt.webChannelTransport, async channel => {
    bridge = channel.objects.reader
    try {
        documentInfo = JSON.parse(await new Promise(resolve => bridge.document(identity, resolve)))
        if (!documentInfo.epub) return
        const bytes = Uint8Array.from(atob(documentInfo.epub), char => char.charCodeAt(0))
        book = await makeBook(new File([bytes], 'material.epub', { type: 'application/epub+zip' }))
        view.addEventListener('external-link', event => event.preventDefault())
        view.addEventListener('link', event => {
            const target = book.resolveHref(event.detail.href)
            if (!target || !documentInfo.chapters.some(chapter => chapter.href === book.sections[target.index]?.id)) event.preventDefault()
        })
        for (const section of book.sections) if (!documentInfo.chapters.some(chapter => chapter.href === section.id)) section.linear = 'no'
        // QML owns the authorized chapter menu; book links stay within indexed content.
        view.addEventListener('load', ({detail: {doc}}) => installDocument(doc))
        view.addEventListener('relocate', ({detail}) => {
            if (!ready || !detail.range) return
            const selected = sourceSelection(detail.range)
            if (selected) {
                clearTimeout(locationTimer)
                locationTimer = setTimeout(() => bridge.location(identity, selected[0]), 120)
            }
        })
        await view.open(book)
        view.renderer.setAttribute('flow', 'scrolled')
        view.renderer.setAttribute('max-inline-size', '680px')
        view.renderer.setAttribute('gap', '9%')
        setAppearance(appearance)
        ready = true
        const target = documentInfo.target
        await showSelection(target?.[0] ?? documentInfo.position, target?.[1] ?? documentInfo.position + 1, !!target)
        if (pendingSelection) { const pending = pendingSelection; pendingSelection = null; await showSelection(...pending) }
        bridge.ready(identity)
    } catch(error) {
        bridge.failed(identity)
    }
})
