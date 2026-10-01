import { cx } from '../../ui'

/** Citation chip: evidence id, with the evidence text revealed on hover/focus. */
export default function Cite({ id, text, onRemove, n }: { id: string; text?: string; onRemove?: () => void; n?: number }) {
  return (
    <span className="group/cite relative inline-flex">
      <span tabIndex={0} className={cx('chip cursor-help transition-colors', text ? 'hover:bg-rust-soft hover:text-rust' : 'border-bad/40 bg-bad-soft text-bad')}>
        {n !== undefined && <sup className="font-serif text-[10px] text-rust">{n}</sup>}
        {id}
        {onRemove && (
          <button type="button" className="ml-0.5 text-faint hover:text-bad" onClick={onRemove} aria-label={`Remove source ${id}`}>×</button>
        )}
      </span>
      <span className="pointer-events-none absolute bottom-full left-0 z-40 mb-2 hidden w-80 rounded border border-rule bg-ink px-3 py-2 text-xs leading-relaxed text-sheet shadow-lg group-hover/cite:block group-focus-within/cite:block">
        {text ?? 'Unknown evidence id'}
      </span>
    </span>
  )
}
