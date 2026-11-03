import { motion } from 'framer-motion';

/**
 * Fades content upward into view. Used for hero/page-load sequences.
 * Props:
 *  - delay: seconds before animation starts
 *  - y: initial vertical offset in px
 *  - duration: animation duration in seconds
 */
export default function FadeIn({ children, delay = 0, y = 18, duration = 0.7, className = '', as = 'div', ...rest }) {
  const Component = motion[as] || motion.div;
  return (
    <Component
      className={className}
      initial={{ opacity: 0, y }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration, delay, ease: [0.16, 1, 0.3, 1] }}
      {...rest}
    >
      {children}
    </Component>
  );
}
