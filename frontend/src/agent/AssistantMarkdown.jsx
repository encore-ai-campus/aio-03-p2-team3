import { useState } from "react"
import Markdown, { defaultUrlTransform } from "react-markdown"
import remarkBreaks from "remark-breaks"
import remarkGfm from "remark-gfm"

import { appHref } from "../api"

const markdownFence = /^ {0,3}(\x60{3,}|~{3,})(?:md|markdown)[ \t]*\r?\n([\s\S]*?)\r?\n {0,3}\1[ \t]*$/i

function CopyButton({ text }) {
  const [feedback, setFeedback] = useState(null)

  async function copy(event) {
    const button = event.currentTarget
    try {
      await navigator.clipboard.writeText(text)
      setFeedback("복사됨")
    } catch {
      const area = document.createElement("textarea")
      area.value = text
      document.body.appendChild(area)
      area.select()
      try {
        setFeedback(document.execCommand("copy") ? "복사됨" : "복사 실패")
      } catch {
        setFeedback("복사 실패")
      } finally {
        area.remove()
        button.focus()
      }
    }
  }

  return <button type="button" className="copy" onClick={copy}>{feedback || "복사"}</button>
}

const components = {
  a: ({ href, children }) => href
    ? <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>
    : <span>{children}</span>,
  img: ({ alt }) => alt ? <span>{alt}</span> : null,
  table: ({ children }) => <div className="table-scroll" tabIndex={0} role="region" aria-label="표 · 가로 스크롤">
    <table>{children}</table>
  </div>,
  pre: ({ children }) => {
    const content = children?.props?.children
    const raw = Array.isArray(content) ? content.join("") : String(content ?? "")
    const language = children?.props?.className?.match(/\blanguage-([^\s]+)/)?.[1]
    return <div className="codeblock">
      <div className="codeblock-bar">
        <span>{language || "코드"}</span>
        <CopyButton text={raw} />
      </div>
      <pre tabIndex={0} role="region" aria-label="코드 · 가로 스크롤">{children}</pre>
    </div>
  },
}

export default function AssistantMarkdown({ text }) {
  // A reply wrapped as a Markdown document is prose. Other code fences are preserved.
  const cleaned = text.replace(/^(?:[ \t]*\r?\n)+|(?:\r?\n[ \t]*)+$/g, "")
  const source = cleaned.match(markdownFence)?.[2] ?? text
  // 답변 마크다운의 /app 링크는 실제 서비스 경로(같은 출처 /app·정적 사이트 루트)로 바꾼다.
  const urlTransform = (url) => appHref(defaultUrlTransform(url))
  return <Markdown skipHtml remarkPlugins={[remarkGfm, remarkBreaks]} components={components}
    urlTransform={urlTransform}>{source}</Markdown>
}
