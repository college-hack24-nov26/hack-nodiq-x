import './Button.css';

/**
 * variant: 'primary' | 'secondary' | 'ghost'
 * size: 'md' | 'lg'
 */
export default function Button({
  children,
  variant = 'primary',
  size = 'md',
  as = 'button',
  className = '',
  ...rest
}) {
  const Component = as;
  return (
    <Component className={`btn btn--${variant} btn--${size} ${className}`} {...rest}>
      {children}
    </Component>
  );
}
