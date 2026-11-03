import "./PageHeader.css";

/**
 * Shared page header for dashboard pages.
 *
 *   eyebrow    — small mono section label (e.g. "QUALITY CONTROL")
 *   title      — h1 page title
 *   description— one-line supporting sentence
 *   actions    — node, right-aligned action area (buttons, filters)
 *
 * Purely presentational: no data, no API, no routing.
 */
export default function PageHeader({ eyebrow, title, description, actions }) {
  return (
    <header className="page-header">
      <div className="page-header__text">
        {eyebrow && <p className="page-header__eyebrow">{eyebrow}</p>}
        <h1 className="page-header__title">{title}</h1>
        {description && <p className="page-header__desc">{description}</p>}
      </div>
      {actions && <div className="page-header__actions">{actions}</div>}
    </header>
  );
}
