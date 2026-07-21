export function PixelBot({ small = false }: { small?: boolean }) {
  return (
    <div className={`pixel-bot ${small ? 'pixel-bot--small' : ''}`} aria-hidden="true">
      <span className="bot-antenna" />
      <span className="bot-ear bot-ear--left" />
      <span className="bot-face">
        <i className="bot-eye bot-eye--left" />
        <i className="bot-eye bot-eye--right" />
        <i className="bot-mouth" />
      </span>
      <span className="bot-ear bot-ear--right" />
      {!small && <span className="bot-shadow" />}
    </div>
  )
}
