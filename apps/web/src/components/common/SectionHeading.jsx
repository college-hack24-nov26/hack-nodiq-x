/**
 * SectionHeading — renders an h2 with the last `accentFrom` words wrapped in
 * .heading-word--accent so the white→orange gradient (dark) / ink→orange
 * gradient (light) always breaks between words, never mid-glyph
 * (usability audit issues 6/14: mid-word color splits hurt readability).
 */
export default function SectionHeading({ text, accentFrom = 2, as: Tag = 'h2', className = '' }) {
  const words = text.split(' ');
  const splitAt = Math.max(0, words.length - accentFrom);
  return (
    <Tag className={`section-heading ${className}`}>
      {words.map((word, i) =>
        i < splitAt ? (
          <span key={i} className="heading-word">{word}{i < words.length - 1 ? ' ' : ''}</span>
        ) : (
          <span key={i} className="heading-word heading-word--accent">{word}{i < words.length - 1 ? ' ' : ''}</span>
        )
      )}
    </Tag>
  );
}
