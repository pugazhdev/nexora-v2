import { ImagePlus, X } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Button } from '@/components/ui/Button'
import { Glass } from '@/components/ui/Glass'
import { stepsFor } from '@/components/shell/steps'
import { Topbar } from '@/components/shell/Topbar'
import { Spinner } from '@/components/ui/Spinner'
import { useAnalyse } from './useResearch'

const TYPES = ['image/jpeg', 'image/png', 'image/webp']
const MAX = 8 * 1024 * 1024

export function InputStep() {
  const nav = useNavigate()
  const analyse = useAnalyse()
  const [text, setText] = useState('')
  const [image, setImage] = useState<File | null>(null)
  const [fileError, setFileError] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [over, setOver] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)
  const busy = analyse.isPending
  const preview = useMemo(() => (image ? URL.createObjectURL(image) : null), [image])
  useEffect(() => () => void (preview && URL.revokeObjectURL(preview)), [preview])

  const take = useCallback((f: File | undefined) => {
    if (!f) return
    setMessage(null)
    if (!TYPES.includes(f.type)) return setFileError('Use a JPG, PNG or WebP image.')
    if (f.size > MAX) return setFileError('That image is over 8 MB. Use a smaller one.')
    setFileError(null)
    setImage(f)
  }, [])

  useEffect(() => {
    if (busy) return
    const onPaste = (e: ClipboardEvent) => {
      const f = [...(e.clipboardData?.files ?? [])].find((x) => x.type.startsWith('image/'))
      if (f) {
        e.preventDefault()
        take(f)
      }
    }
    document.addEventListener('paste', onPaste)
    return () => document.removeEventListener('paste', onPaste)
  }, [busy, take])

  const submit = () => {
    setFileError(null)
    setMessage(null)
    analyse.mutate(
      { image, text },
      {
        onSuccess: (r) =>
          r.items.some((i) => i.in_scope)
            ? nav(`/research/${r.id}`)
            : setMessage(r.message ?? 'No consumables found. Add a clearer photo or paste the requirement as text.'),
      },
    )
  }

  const error = fileError ?? analyse.error?.message ?? message
  const ready = !!image || text.trim().length > 0

  return (
    <>
      <Topbar crumb={<b>New research</b>} steps={stepsFor(0)} current="Input" />
      <div className="view narrow">
        <h1>New research</h1>
        <div className="muted">Add a photo or paste the requirement. You will confirm before anything is searched.</div>
        <div className="input-grid">
          <Glass className="p">
            <div
              className={`drop${over ? ' over' : ''}`}
              onDragOver={(e) => {
                e.preventDefault()
                setOver(true)
              }}
              onDragLeave={() => setOver(false)}
              onDrop={(e) => {
                e.preventDefault()
                setOver(false)
                if (!busy) take(e.dataTransfer.files[0])
              }}
            >
              {preview ? (
                <div className="thumb">
                  <img src={preview} alt="Selected photo" />
                  <button
                    type="button"
                    className="thumb-x"
                    aria-label="Remove image"
                    disabled={busy}
                    onClick={() => {
                      setImage(null)
                      setFileError(null)
                    }}
                  >
                    <X size={14} />
                  </button>
                </div>
              ) : (
                <button type="button" className="drop-btn" disabled={busy} onClick={() => fileRef.current?.click()}>
                  <ImagePlus size={22} aria-hidden />
                  <b>Drop an image</b>
                  <span className="muted">or click to browse, or paste. JPG, PNG, WebP</span>
                </button>
              )}
              <input
                ref={fileRef}
                type="file"
                hidden
                aria-label="Choose an image"
                accept={TYPES.join(',')}
                onChange={(e) => {
                  take(e.target.files?.[0])
                  e.target.value = ''
                }}
              />
            </div>
          </Glass>
          <Glass className="p">
            <textarea
              aria-label="Requirement"
              value={text}
              disabled={busy}
              onChange={(e) => {
                setText(e.target.value)
                setFileError(null)
              }}
              placeholder={'Paste the requirement, e.g.\n2 mL disposable syringe with needle, 24G, 50,000 nos'}
            />
          </Glass>
        </div>
        {error && (
          <p className="field-error" role="alert">
            {error}
          </p>
        )}
        <div className="actions">
          <Button disabled={!ready || busy} onClick={submit}>
            {busy ? (
              <>
                <Spinner label="Analysing" /> Analysing...
              </>
            ) : (
              'Analyse'
            )}
          </Button>
          {busy && <span className="muted">Reading the photo and requirement</span>}
        </div>
      </div>
    </>
  )
}
