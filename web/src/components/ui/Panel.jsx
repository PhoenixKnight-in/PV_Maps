/**
 * Spatial inspector card. 36px header with a lighter bottom separator than the
 * panel's own border, per the design system's construction note.
 *
 * `floating` switches the surface to the Level-2 HUD glass used for panels that
 * sit over the spatial canvas.
 */
export default function Panel({
  title,
  aside,
  children,
  floating = false,
  className = "",
  bodyClass = "",
}) {
  return (
    <section className={`${floating ? "hud" : "panel"} ${className}`}>
      {(title || aside) && (
        <header className="panel-head">
          {title && <h3 className="panel-title">{title}</h3>}
          {aside}
        </header>
      )}
      <div className={`panel-body ${bodyClass}`}>{children}</div>
    </section>
  );
}
