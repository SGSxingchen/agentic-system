import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import './Select.css'

export interface SelectOption {
  value: string
  label: string
  description?: string
  disabled?: boolean
}

interface SelectProps {
  value: string
  options: SelectOption[]
  onChange: (value: string) => void
  disabled?: boolean
  placeholder?: string
  size?: 'sm' | 'md'
  fullWidth?: boolean
  /**
   * Render the trigger label. Defaults to the matching option's label or value.
   */
  renderTrigger?: (selected: SelectOption | undefined) => React.ReactNode
}

export function Select({
  value,
  options,
  onChange,
  disabled = false,
  placeholder = '请选择',
  size = 'md',
  fullWidth = true,
  renderTrigger,
}: SelectProps) {
  const [open, setOpen] = useState(false)
  const containerRef = useRef<HTMLDivElement | null>(null)
  const triggerRef = useRef<HTMLButtonElement | null>(null)
  const popupRef = useRef<HTMLDivElement | null>(null)
  const [popupPos, setPopupPos] = useState<{
    top: number
    left: number
    width: number
    direction: 'down' | 'up'
  } | null>(null)

  const selected = options.find((option) => option.value === value)

  useEffect(() => {
    if (!open) return
    const handleClickOutside = (event: MouseEvent) => {
      const target = event.target as Node
      if (containerRef.current?.contains(target)) return
      if (popupRef.current?.contains(target)) return
      setOpen(false)
    }
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }
    const handleScroll = () => setOpen(false)
    document.addEventListener('mousedown', handleClickOutside)
    document.addEventListener('keydown', handleKey)
    window.addEventListener('scroll', handleScroll, true)
    window.addEventListener('resize', handleScroll)
    return () => {
      document.removeEventListener('mousedown', handleClickOutside)
      document.removeEventListener('keydown', handleKey)
      window.removeEventListener('scroll', handleScroll, true)
      window.removeEventListener('resize', handleScroll)
    }
  }, [open])

  useLayoutEffect(() => {
    if (!open || !triggerRef.current) return
    const rect = triggerRef.current.getBoundingClientRect()
    const viewportHeight = window.innerHeight
    const spaceBelow = viewportHeight - rect.bottom
    const desiredHeight = 320
    const direction = spaceBelow < desiredHeight && rect.top > spaceBelow ? 'up' : 'down'
    setPopupPos({
      top: direction === 'down' ? rect.bottom + 4 : rect.top - 4,
      left: rect.left,
      width: rect.width,
      direction,
    })
  }, [open])

  const handleSelect = (optionValue: string) => {
    onChange(optionValue)
    setOpen(false)
  }

  return (
    <div
      className={`select ${fullWidth ? 'select--full' : ''}`}
      ref={containerRef}
    >
      <button
        ref={triggerRef}
        type="button"
        className={`select__trigger select__trigger--${size} ${
          open ? 'select__trigger--open' : ''
        }`}
        onClick={() => !disabled && setOpen((prev) => !prev)}
        disabled={disabled}
      >
        <span className="select__value">
          {renderTrigger
            ? renderTrigger(selected)
            : selected?.label || (
                <span className="select__placeholder">{placeholder}</span>
              )}
        </span>
        <svg
          className={`select__chevron ${open ? 'select__chevron--open' : ''}`}
          width="11"
          height="11"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <polyline points="6 9 12 15 18 9" />
        </svg>
      </button>
      {open && popupPos && (
        <div
          ref={popupRef}
          className="select__popup"
          style={{
            position: 'fixed',
            top:
              popupPos.direction === 'down'
                ? popupPos.top
                : undefined,
            bottom:
              popupPos.direction === 'up'
                ? window.innerHeight - popupPos.top
                : undefined,
            left: popupPos.left,
            width: popupPos.width,
          }}
        >
          {options.length === 0 ? (
            <div className="select__empty">无可选项</div>
          ) : (
            options.map((option) => {
              const isActive = option.value === value
              return (
                <button
                  key={option.value}
                  type="button"
                  className={`select__option ${
                    isActive ? 'select__option--active' : ''
                  } ${option.disabled ? 'select__option--disabled' : ''}`}
                  disabled={option.disabled}
                  onClick={() => handleSelect(option.value)}
                >
                  <span className="select__option-label">{option.label}</span>
                  {option.description && (
                    <span className="select__option-desc">{option.description}</span>
                  )}
                </button>
              )
            })
          )}
        </div>
      )}
    </div>
  )
}
