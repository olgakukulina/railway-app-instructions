import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  createTask,
  deleteTask,
  downloadTask,
  getTaskContent,
  getTaskStatus,
  getTasks,
  hasSession,
  login,
  logout,
  register,
  saveTaskContent,
} from './api'
import {
  ACTIVE_STATUSES,
  PROCESSING_STEPS,
  STATIONS,
  STATUS_META,
} from './constants'
import { exportInstructionDocx, exportInstructionPdf } from './documentExport'

const PROFILE_KEY = 'railway-user-profile'
const POLLING_INTERVAL_MS = 3000

function readProfile() {
  try {
    return JSON.parse(localStorage.getItem(PROFILE_KEY) || '{}')
  } catch {
    return {}
  }
}

function saveProfile(profile) {
  localStorage.setItem(PROFILE_KEY, JSON.stringify(profile))
}

function formatDate(value) {
  if (!value) return 'Дата не указана'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)

  return new Intl.DateTimeFormat('ru-RU', {
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date)
}

function getTaskId(task) {
  return task?.id || task?.taskId
}

function getTaskStatusValue(task) {
  return task?.status || 'CREATED'
}

function getTaskFileName(task) {
  return task?.originalFileName || task?.fileName || task?.filename || 'Технический паспорт'
}

function getTaskStation(task) {
  return task?.station || task?.stationName || ''
}

function getTaskTitle(task, instruction) {
  return (
    instruction?.company ||
    task?.company ||
    task?.ownerName ||
    getTaskFileName(task).replace(/\.[^.]+$/, '')
  )
}

function normalizeStatusResponse(task, response) {
  if (typeof response === 'string') return { ...task, status: response }
  return { ...task, ...(response || {}) }
}

function normalizeInstructionResponse(response, task) {
  if (typeof response === 'string') {
    return {
      taskId: getTaskId(task),
      content: response,
      station: getTaskStation(task),
    }
  }

  const nested = response?.instruction || response?.data || response?.result || {}
  const content =
    response?.content ||
    response?.instructionText ||
    response?.text ||
    nested?.content ||
    nested?.instructionText ||
    nested?.text

  if (typeof content !== 'string') {
    throw new Error('Gateway не вернул текст инструкции в поле content.')
  }

  return {
    taskId: getTaskId(task),
    company: '',
    station: getTaskStation(task),
    pathNumber: '',
    locomotives: '',
    connection: '',
    boundary: '',
    safety: '',
    ...nested,
    ...response,
    content,
  }
}

function TrashIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M9 3h6l1 2h4v2H4V5h4l1-2Zm-2 6h10l-.7 11H7.7L7 9Zm3 2v7h2v-7h-2Zm4 0v7h2v-7h-2Z" />
    </svg>
  )
}

function AuthPage({ onAuthenticated }) {
  const [mode, setMode] = useState('login')
  const [form, setForm] = useState({
    username: '',
    email: '',
    password: '',
    firstName: '',
    lastName: '',
  })
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  function updateField(event) {
    setForm((current) => ({ ...current, [event.target.name]: event.target.value }))
  }

  async function handleSubmit(event) {
    event.preventDefault()
    setSubmitting(true)
    setError('')

    try {
      if (mode === 'login') {
        await login({
          username: form.username.trim(),
          password: form.password,
        })

        onAuthenticated({ username: form.username.trim() })
        return
      }

      await register({
        username: form.username.trim(),
        email: form.email.trim(),
        password: form.password,
        firstName: form.firstName.trim(),
        lastName: form.lastName.trim(),
      })

      onAuthenticated({
        username: form.username.trim(),
        firstName: form.firstName.trim(),
        lastName: form.lastName.trim(),
      })
    } catch (requestError) {
      setError(requestError.message || 'Не удалось выполнить запрос.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main className="auth-page">
      <section className="auth-card">
        <div className="auth-brand">
          <div className="brand-mark">РЖД</div>
          <div>
            <strong>Авто Инструкция</strong>
            <span>Генерация документов по техническим паспортам</span>
          </div>
        </div>

        <div className="auth-tabs">
          <button
            type="button"
            className={mode === 'login' ? 'auth-tab-active' : ''}
            onClick={() => {
              setMode('login')
              setError('')
            }}
          >
            Вход
          </button>
          <button
            type="button"
            className={mode === 'register' ? 'auth-tab-active' : ''}
            onClick={() => {
              setMode('register')
              setError('')
            }}
          >
            Регистрация
          </button>
        </div>

        <div className="auth-heading">
          <h1>{mode === 'login' ? 'Войдите в систему' : 'Создайте аккаунт'}</h1>
          <p>
            {mode === 'login'
              ? 'Используйте имя пользователя и пароль.'
              : 'Заполните данные, чтобы начать работу с инструкциями.'}
          </p>
        </div>

        <form className="auth-form" onSubmit={handleSubmit}>
          {mode === 'register' && (
            <div className="auth-row">
              <label>
                <span>Имя</span>
                <input
                  name="firstName"
                  value={form.firstName}
                  onChange={updateField}
                  autoComplete="given-name"
                  required
                />
              </label>
              <label>
                <span>Фамилия</span>
                <input
                  name="lastName"
                  value={form.lastName}
                  onChange={updateField}
                  autoComplete="family-name"
                  required
                />
              </label>
            </div>
          )}

          <label>
            <span>Имя пользователя</span>
            <input
              name="username"
              value={form.username}
              onChange={updateField}
              autoComplete="username"
              minLength={3}
              required
            />
          </label>

          {mode === 'register' && (
            <label>
              <span>Email</span>
              <input
                name="email"
                type="email"
                value={form.email}
                onChange={updateField}
                autoComplete="email"
                required
              />
            </label>
          )}

          <label>
            <span>Пароль</span>
            <input
              name="password"
              type="password"
              value={form.password}
              onChange={updateField}
              autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
              minLength={8}
              maxLength={100}
              required
            />
          </label>

          {error && <div className="form-error">{error}</div>}

          <button type="submit" className="primary-button wide-button" disabled={submitting}>
            {submitting ? 'Отправка…' : mode === 'login' ? 'Войти' : 'Зарегистрироваться'}
          </button>
        </form>
      </section>
    </main>
  )
}

function UploadCard({ file, setFile }) {
  const inputRef = useRef(null)
  const [dragging, setDragging] = useState(false)

  function validateAndSet(nextFile) {
    if (!nextFile) return

    const extension = nextFile.name.split('.').pop()?.toLowerCase()
    if (!['pdf', 'doc', 'docx'].includes(extension)) {
      window.alert('Поддерживаются только PDF, DOC и DOCX')
      return
    }

    setFile(nextFile)
  }

  return (
    <div
      className={`upload-card ${dragging ? 'upload-card-dragging' : ''}`}
      onDragOver={(event) => {
        event.preventDefault()
        setDragging(true)
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(event) => {
        event.preventDefault()
        setDragging(false)
        validateAndSet(event.dataTransfer.files?.[0])
      }}
    >
      <input
        ref={inputRef}
        hidden
        type="file"
        accept=".pdf,.doc,.docx"
        onChange={(event) => validateAndSet(event.target.files?.[0])}
      />

      {!file ? (
        <>
          <div className="upload-icon">⇧</div>
          <h3>Загрузите технический паспорт</h3>
          <p>PDF, DOC или DOCX</p>
          <button type="button" className="secondary-button" onClick={() => inputRef.current?.click()}>
            Выбрать файл
          </button>
        </>
      ) : (
        <div className="selected-file">
          <div className="file-icon">DOC</div>
          <div>
            <strong>{file.name}</strong>
            <span>{Math.max(1, Math.round(file.size / 1024))} КБ</span>
          </div>
          <button type="button" className="text-button" onClick={() => setFile(null)}>
            Удалить
          </button>
        </div>
      )}
    </div>
  )
}

function NewInstructionView({ onCreate }) {
  const [station, setStation] = useState(STATIONS[0])
  const [file, setFile] = useState(null)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  async function handleCreate() {
    if (!file) return

    setSubmitting(true)
    setError('')

    try {
      await onCreate({ station, file })
    } catch (requestError) {
      setError(requestError.message || 'Не удалось загрузить документ.')
      setSubmitting(false)
    }
  }

  return (
    <main className="workspace center-workspace">
      <section className="new-card">
        <h1>Создайте инструкцию по техническому паспорту</h1>
        <p className="lead">Выберите станцию и загрузите паспорт железнодорожного пути.</p>

        <label className="field-label" htmlFor="station">
          Железнодорожная станция
        </label>
        <select
          id="station"
          className="select"
          value={station}
          onChange={(event) => setStation(event.target.value)}
        >
          {STATIONS.map((item) => (
            <option key={item} value={item}>{item}</option>
          ))}
        </select>

        <UploadCard file={file} setFile={setFile} />

        {error && <div className="form-error upload-error">{error}</div>}

        <button
          type="button"
          className="primary-button wide-button"
          disabled={!file || submitting}
          onClick={handleCreate}
        >
          {submitting ? 'Загружаем…' : 'Создать инструкцию'}
        </button>
      </section>
    </main>
  )
}

function ProcessingView({ task }) {
  const status = getTaskStatusValue(task)
  const meta = STATUS_META[status] || STATUS_META.CREATED

  return (
    <main className="workspace chat-workspace">
      <div className="chat-shell">
        <div className="chat-message chat-message-user">
          <div className="chat-avatar">Вы</div>
          <div className="chat-bubble">
            <strong>Создать инструкцию для станции {getTaskStation(task) || 'не указана'}</strong>
            <span className="file-pill">📄 {getTaskFileName(task)}</span>
          </div>
        </div>

        <div className="chat-message">
          <div className="chat-avatar system-avatar">AI</div>
          <div className="chat-bubble system-bubble">
            <strong>Обрабатываю технический паспорт</strong>

            <div className="progress-track">
              <div className="progress-value" style={{ width: `${meta.progress}%` }} />
            </div>

            <div className="progress-row">
              <span>{meta.label}</span>
              <strong>{meta.progress}%</strong>
            </div>

            <div className="steps">
              {PROCESSING_STEPS.map((step, index) => (
                <div
                  key={step}
                  className={`step ${index < meta.step ? 'step-done' : ''} ${
                    index === meta.step ? 'step-active' : ''
                  }`}
                >
                  <span>{index < meta.step ? '✓' : index + 1}</span>
                  {step}
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </main>
  )
}

function FailedTaskView({ task, onRefresh, refreshing }) {
  return (
    <main className="workspace task-workspace">
      <header className="editor-header">
        <div>
          <h1>{getTaskTitle(task)}</h1>
          <p>{getTaskStation(task) || 'Станция не указана'} · {getTaskFileName(task)}</p>
        </div>
        <button type="button" className="secondary-button" onClick={onRefresh} disabled={refreshing}>
          {refreshing ? 'Обновление…' : 'Обновить статус'}
        </button>
      </header>

      <section className="task-content">
        <div className="task-hero">
          <div className="status-icon status-icon-error">!</div>
          <div>
            <span className="status-badge status-failed">Ошибка</span>
            <h2>Обработка завершилась с ошибкой</h2>
            <p>{task.errorMessage || 'Gateway не передал подробности ошибки.'}</p>
          </div>
        </div>
      </section>
    </main>
  )
}

function DataSummary({ instruction, task }) {
  return (
    <div className="summary-grid">
      <div><span>Владелец</span><strong>{instruction.company || 'Не определён'}</strong></div>
      <div><span>Станция</span><strong>{instruction.station || getTaskStation(task) || 'Не указана'}</strong></div>
      <div><span>Путь</span><strong>{instruction.pathNumber || 'Не определён'}</strong></div>
      <div><span>Локомотивы</span><strong>{instruction.locomotives || 'Не определены'}</strong></div>
      <div className="summary-wide"><span>Примыкание</span><strong>{instruction.connection || 'Не определено'}</strong></div>
      <div className="summary-wide"><span>Предохранительные устройства</span><strong>{instruction.safety || 'Не определены'}</strong></div>
    </div>
  )
}

function EditorView({
  task,
  instruction,
  loading,
  error,
  saveState,
  exporting,
  onRetry,
  onChange,
  onSave,
  onExportPdf,
  onExportDocx,
  onDownloadResult,
}) {
  const title = getTaskTitle(task, instruction)
  const downloadOnly = Boolean(instruction?.downloadOnly)

  return (
    <main className="workspace editor-workspace">
      <header className="editor-header">
        <div>
          <h1>{title}</h1>
          <p>{instruction?.station || getTaskStation(task) || 'Станция не указана'} · {getTaskFileName(task)}</p>
        </div>

        <div className="header-actions">
          <button
            type="button"
            className="primary-button"
            disabled={Boolean(exporting)}
            onClick={onDownloadResult}
          >
            {exporting === 'result' ? 'Скачивание…' : 'Скачать результат'}
          </button>
          {!downloadOnly && (
            <>
              <button
                type="button"
                className="secondary-button"
                disabled={!instruction || Boolean(exporting)}
                onClick={onExportPdf}
              >
                {exporting === 'pdf' ? 'Формирование…' : 'PDF (локально)'}
              </button>
              <button
                type="button"
                className="secondary-button"
                disabled={!instruction || Boolean(exporting)}
                onClick={onExportDocx}
              >
                {exporting === 'docx' ? 'Формирование…' : 'DOCX (локально)'}
              </button>
              <button
                type="button"
                className="secondary-button"
                disabled={!instruction || saveState === 'saving' || saveState === 'saved'}
                onClick={onSave}
              >
                {saveState === 'saving' ? 'Сохраняем…' : 'Сохранить'}
              </button>
            </>
          )}
        </div>
      </header>

      <section className="document-area">
        {loading && <div className="content-loader">Загружаем содержимое инструкции…</div>}

        {!loading && error && (
          <div className="editor-message editor-message-error">
            <span>{error}</span>
            <button type="button" className="secondary-button" onClick={onRetry}>Повторить</button>
            <button type="button" className="primary-button" onClick={onDownloadResult}>Скачать результат из Gateway</button>
          </div>
        )}

        {!loading && !error && instruction && downloadOnly && (
          <div className="editor-message">
            <p><strong>Инструкция собрана успешно.</strong></p>
            <p>
              Текст для редактора временно недоступен — скачай готовый PDF кнопкой
              <strong> «Скачать результат»</strong>.
            </p>
            <button type="button" className="primary-button" onClick={onDownloadResult} disabled={Boolean(exporting)}>
              {exporting === 'result' ? 'Скачивание…' : 'Скачать результат'}
            </button>
          </div>
        )}

        {!loading && !error && instruction && !downloadOnly && (
          <>
            <DataSummary instruction={instruction} task={task} />

            <div className="document-toolbar">
              <strong>Редактор инструкции</strong>
              <span>
                {saveState === 'dirty' && 'Есть несохранённые изменения'}
                {saveState === 'saving' && 'Сохранение…'}
                {saveState === 'saved' && 'Изменения сохранены'}
                {saveState === 'idle' && 'Документ загружен из Gateway'}
              </span>
            </div>

            <textarea
              className="document-editor"
              value={instruction.content}
              spellCheck="true"
              onChange={(event) => onChange(event.target.value)}
            />
          </>
        )}
      </section>
    </main>
  )
}

function TaskItem({ task, active, onOpen, onDelete }) {
  const status = getTaskStatusValue(task)
  const meta = STATUS_META[status] || STATUS_META.CREATED

  return (
    <div className={`instruction-item ${active ? 'instruction-item-active' : ''}`}>
      <button type="button" className="instruction-open-button" onClick={onOpen}>
        <span className="instruction-item-title">{getTaskTitle(task)}</span>
        <span className="instruction-item-meta">{getTaskStation(task) || meta.label}</span>
        <span className="instruction-item-date">{formatDate(task.updatedAt || task.createdAt)}</span>
      </button>

      <button
        type="button"
        className="instruction-delete-button"
        aria-label={`Удалить задачу ${getTaskTitle(task)}`}
        title="Удалить задачу"
        onClick={onDelete}
      >
        <TrashIcon />
      </button>
    </div>
  )
}

function DeleteTaskModal({ task, onCancel, onConfirm, deleting }) {
  if (!task) return null

  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={onCancel}>
      <div
        className="confirm-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="delete-modal-title"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="confirm-modal-icon"><TrashIcon /></div>
        <h2 id="delete-modal-title">Удалить инструкцию?</h2>
        <p>Документ «{getTaskFileName(task)}» будет удалён без возможности восстановления.</p>
        <div className="confirm-modal-actions">
          <button type="button" className="secondary-button" onClick={onCancel} disabled={deleting}>
            Отмена
          </button>
          <button type="button" className="delete-confirm-button" onClick={onConfirm} disabled={deleting}>
            {deleting ? 'Удаление…' : 'Удалить'}
          </button>
        </div>
      </div>
    </div>
  )
}

export default function App() {
  const [authenticated, setAuthenticated] = useState(hasSession)
  const [profile, setProfile] = useState(readProfile)
  const [tasks, setTasks] = useState([])
  const [activeId, setActiveId] = useState(null)
  const [view, setView] = useState('new')
  const [loadingTasks, setLoadingTasks] = useState(false)
  const [loadError, setLoadError] = useState('')
  const [instruction, setInstruction] = useState(null)
  const [contentLoading, setContentLoading] = useState(false)
  const [contentError, setContentError] = useState('')
  const [saveState, setSaveState] = useState('idle')
  const [deleteTarget, setDeleteTarget] = useState(null)
  const [deleting, setDeleting] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [exporting, setExporting] = useState('')
  const pollingInProgress = useRef(false)

  const activeTask = useMemo(
    () => tasks.find((task) => getTaskId(task) === activeId) || null,
    [tasks, activeId],
  )

  const activeTaskIds = useMemo(
    () => tasks
      .filter((task) => ACTIVE_STATUSES.has(getTaskStatusValue(task)))
      .map(getTaskId)
      .filter(Boolean),
    [tasks],
  )

  const updateTask = useCallback((id, patch) => {
    setTasks((current) => current.map((task) => (
      getTaskId(task) === id ? { ...task, ...patch } : task
    )))
  }, [])

  const loadTaskList = useCallback(async ({ silent = false } = {}) => {
    if (!silent) setLoadingTasks(true)
    setLoadError('')

    try {
      const nextTasks = await getTasks()
      setTasks(nextTasks)

      setActiveId((currentId) => {
        if (currentId && nextTasks.some((task) => getTaskId(task) === currentId)) {
          return currentId
        }
        return null
      })
    } catch (error) {
      if (error.status === 401) {
        setAuthenticated(false)
      } else {
        setLoadError(error.message || 'Не удалось загрузить задачи.')
      }
    } finally {
      if (!silent) setLoadingTasks(false)
    }
  }, [])

  const loadInstruction = useCallback(async (task) => {
    if (!task) return

    setContentLoading(true)
    setContentError('')
    setInstruction(null)
    setSaveState('idle')

    const taskId = getTaskId(task)

    try {
      const response = await getTaskContent(taskId)
      setInstruction(normalizeInstructionResponse(response, task))
    } catch (error) {
      const missingContent =
        error?.status === 404
        || error?.status === 500
        || /unexpected error|No static resource|\/content/i.test(String(error?.message || ''))

      if (missingContent) {
        setInstruction({
          taskId,
          downloadOnly: true,
          company: '',
          station: getTaskStation(task),
          content: '',
        })
        setContentError('')
      } else {
        setContentError(error.message || 'Не удалось загрузить текст инструкции.')
      }
    } finally {
      setContentLoading(false)
    }
  }, [])

  useEffect(() => {
    function handleUnauthorized() {
      setAuthenticated(false)
      setTasks([])
      setActiveId(null)
      setInstruction(null)
    }

    window.addEventListener('railway:unauthorized', handleUnauthorized)
    return () => window.removeEventListener('railway:unauthorized', handleUnauthorized)
  }, [])

  useEffect(() => {
    if (authenticated) loadTaskList()
  }, [authenticated, loadTaskList])

  useEffect(() => {
    if (!authenticated || activeTaskIds.length === 0) return undefined

    async function pollStatuses() {
      if (pollingInProgress.current) return
      pollingInProgress.current = true

      try {
        const updates = await Promise.allSettled(
          activeTaskIds.map(async (id) => ({ id, response: await getTaskStatus(id) })),
        )

        updates.forEach((result) => {
          if (result.status !== 'fulfilled') return
          const { id, response } = result.value
          setTasks((current) => current.map((task) => (
            getTaskId(task) === id ? normalizeStatusResponse(task, response) : task
          )))
        })
      } finally {
        pollingInProgress.current = false
      }
    }

    pollStatuses()
    const timer = window.setInterval(pollStatuses, POLLING_INTERVAL_MS)
    return () => window.clearInterval(timer)
  }, [authenticated, activeTaskIds.join('|')])

  useEffect(() => {
    if (!activeTask || view !== 'task') {
      setInstruction(null)
      setContentError('')
      return
    }

    if (getTaskStatusValue(activeTask) === 'COMPLETED') {
      loadInstruction(activeTask)
    } else {
      setInstruction(null)
      setContentError('')
    }
  }, [activeId, activeTask?.status, view, loadInstruction])

  useEffect(() => {
    function handleBeforeUnload(event) {
      if (saveState !== 'dirty') return
      event.preventDefault()
      event.returnValue = ''
    }

    window.addEventListener('beforeunload', handleBeforeUnload)
    return () => window.removeEventListener('beforeunload', handleBeforeUnload)
  }, [saveState])

  function handleAuthenticated(nextProfile) {
    saveProfile(nextProfile)
    setProfile(nextProfile)
    setAuthenticated(true)
    setView('new')
  }

  async function handleLogout() {
    try {
      await logout()
    } finally {
      localStorage.removeItem(PROFILE_KEY)
      setAuthenticated(false)
      setProfile({})
      setTasks([])
      setActiveId(null)
      setInstruction(null)
    }
  }

  async function handleCreate({ station, file }) {
    const createdTask = await createTask({ station, file })
    const id = getTaskId(createdTask)

    if (!id) {
      throw new Error('Gateway не вернул id созданной задачи.')
    }

    const normalizedTask = {
      ...createdTask,
      id,
      station: getTaskStation(createdTask) || station,
      originalFileName: getTaskFileName(createdTask) === 'Технический паспорт'
        ? file.name
        : getTaskFileName(createdTask),
    }

    setTasks((current) => [
      normalizedTask,
      ...current.filter((task) => getTaskId(task) !== id),
    ])
    setActiveId(id)
    setView('task')
  }

  async function handleRefreshTask() {
    if (!activeTask) return

    setRefreshing(true)
    try {
      const response = await getTaskStatus(getTaskId(activeTask))
      updateTask(getTaskId(activeTask), normalizeStatusResponse(activeTask, response))
    } catch (error) {
      window.alert(error.message || 'Не удалось обновить статус.')
    } finally {
      setRefreshing(false)
    }
  }

  function handleInstructionChange(content) {
    setInstruction((current) => ({ ...current, content }))
    setSaveState('dirty')
  }

  async function handleSaveInstruction() {
    if (!activeTask || !instruction) return

    setSaveState('saving')
    try {
      const payload = {
        content: instruction.content,
        company: instruction.company || null,
        station: instruction.station || getTaskStation(activeTask) || null,
        pathNumber: instruction.pathNumber || null,
        locomotives: instruction.locomotives || null,
        connection: instruction.connection || null,
        boundary: instruction.boundary || null,
        safety: instruction.safety || null,
      }

      const response = await saveTaskContent(getTaskId(activeTask), payload)
      if (response) {
        setInstruction(normalizeInstructionResponse(response, activeTask))
      }
      setSaveState('saved')
    } catch (error) {
      setSaveState('dirty')
      window.alert(error.message || 'Не удалось сохранить изменения.')
    }
  }

  async function handleDownloadResult() {
    if (!activeTask) return

    setExporting('result')
    try {
      const { blob, contentDisposition, contentType } = await downloadTask(getTaskId(activeTask))
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url

      let filename = 'station-instruction.pdf'
      const match = /filename=\"?([^\";]+)\"?/i.exec(contentDisposition || '')
      if (match?.[1]) filename = match[1]
      else if ((contentType || '').includes('wordprocessingml')) filename = 'station-instruction.docx'

      link.download = filename
      document.body.appendChild(link)
      link.click()
      link.remove()
      URL.revokeObjectURL(url)
    } catch (error) {
      window.alert(error.message || 'Не удалось скачать результат.')
    } finally {
      setExporting('')
    }
  }

  async function handleExportPdf() {
    if (!activeTask || !instruction) return

    setExporting('pdf')
    try {
      await exportInstructionPdf({
        content: instruction.content,
        title: getTaskTitle(activeTask, instruction),
        station: instruction.station || getTaskStation(activeTask) || 'Станция',
        organization: instruction.company || '',
      })
    } catch (error) {
      window.alert(error.message || 'Не удалось сформировать PDF.')
    } finally {
      setExporting('')
    }
  }

  async function handleExportDocx() {
    if (!activeTask || !instruction) return

    setExporting('docx')
    try {
      await exportInstructionDocx({
        content: instruction.content,
        title: getTaskTitle(activeTask, instruction),
        station: instruction.station || getTaskStation(activeTask) || 'Станция',
        organization: instruction.company || '',
      })
    } catch (error) {
      window.alert(error.message || 'Не удалось сформировать DOCX.')
    } finally {
      setExporting('')
    }
  }

  async function handleDelete() {
    if (!deleteTarget) return

    const id = getTaskId(deleteTarget)
    setDeleting(true)

    try {
      await deleteTask(id)
      const nextTasks = tasks.filter((task) => getTaskId(task) !== id)
      setTasks(nextTasks)
      setDeleteTarget(null)

      if (activeId === id) {
        setActiveId(null)
        setView('new')
        setInstruction(null)
      }
    } catch (error) {
      window.alert(error.message || 'Не удалось удалить задачу.')
    } finally {
      setDeleting(false)
    }
  }

  if (!authenticated) {
    return <AuthPage onAuthenticated={handleAuthenticated} />
  }

  const activeStatus = activeTask ? getTaskStatusValue(activeTask) : null

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">РЖД</div>
          <strong>Авто Инструкция</strong>
        </div>

        <button
          type="button"
          className="new-button"
          onClick={() => {
            if (saveState === 'dirty' && !window.confirm('Есть несохранённые изменения. Продолжить?')) return
            setView('new')
            setActiveId(null)
            setInstruction(null)
          }}
        >
          <span>＋</span> Новая инструкция
        </button>

        <div className="sidebar-section-title">Последние инструкции</div>

        <div className="instruction-list">
          {loadingTasks && <div className="sidebar-message">Загружаем…</div>}

          {!loadingTasks && loadError && (
            <button type="button" className="sidebar-retry" onClick={() => loadTaskList()}>
              {loadError}<br />Повторить
            </button>
          )}

          {!loadingTasks && !loadError && tasks.length === 0 && (
            <div className="sidebar-message">Пока нет загруженных документов</div>
          )}

          {tasks.map((task) => {
            const id = getTaskId(task)
            return (
              <TaskItem
                key={id}
                task={task}
                active={view === 'task' && activeId === id}
                onOpen={() => {
                  if (saveState === 'dirty' && !window.confirm('Есть несохранённые изменения. Продолжить?')) return
                  setActiveId(id)
                  setView('task')
                }}
                onDelete={() => setDeleteTarget(task)}
              />
            )
          })}
        </div>

        <div className="sidebar-user">
          <div className="user-avatar">
            {(profile.firstName || profile.username || 'U').slice(0, 1).toUpperCase()}
          </div>
          <div>
            <strong>{[profile.firstName, profile.lastName].filter(Boolean).join(' ') || profile.username}</strong>
            <span>{profile.username}</span>
          </div>
          <button type="button" onClick={handleLogout}>Выйти</button>
        </div>
      </aside>

      {view === 'new' && <NewInstructionView onCreate={handleCreate} />}

      {view === 'task' && activeTask && ACTIVE_STATUSES.has(activeStatus) && (
        <ProcessingView task={activeTask} />
      )}

      {view === 'task' && activeTask && activeStatus === 'FAILED' && (
        <FailedTaskView
          task={activeTask}
          onRefresh={handleRefreshTask}
          refreshing={refreshing}
        />
      )}

      {view === 'task' && activeTask && activeStatus === 'COMPLETED' && (
        <EditorView
          task={activeTask}
          instruction={instruction}
          loading={contentLoading}
          error={contentError}
          saveState={saveState}
          exporting={exporting}
          onRetry={() => loadInstruction(activeTask)}
          onChange={handleInstructionChange}
          onSave={handleSaveInstruction}
          onExportPdf={handleExportPdf}
          onExportDocx={handleExportDocx}
          onDownloadResult={handleDownloadResult}
        />
      )}

      {view === 'task' && !activeTask && <NewInstructionView onCreate={handleCreate} />}

      <DeleteTaskModal
        task={deleteTarget}
        onCancel={() => setDeleteTarget(null)}
        onConfirm={handleDelete}
        deleting={deleting}
      />
    </div>
  )
}