import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

interface Props {
  text: string
  /** 是否还在流式输出中——决定是否在末尾追加闪烁光标 */
  streaming?: boolean
  className?: string
}

/**
 * 统一的 Markdown 渲染：
 * - GFM：表格、删除线、任务列表、自动链接
 * - 链接默认在新标签打开
 * - 不允许自定义 raw HTML（默认行为，安全）
 */
export function Markdown({ text, streaming, className }: Props) {
  return (
    <div className={`md ${className ?? ''}`}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ children, href }) => (
            <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>
          ),
          // table 包一层 div 以支持横向滚动
          table: ({ children }) => (
            <div className="md-table-wrap">
              <table>{children}</table>
            </div>
          ),
        }}
      >
        {text || ''}
      </ReactMarkdown>
      {streaming && <span className="ai-cursor" />}
    </div>
  )
}
