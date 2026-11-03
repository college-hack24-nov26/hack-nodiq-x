import { motion } from 'framer-motion';

/**
 * Slides content up slightly with a fade. Intended for use inside a
 * staggered parent (see Reveal.jsx) so children animate in sequence.
 */
export default function SlideUp({ children, className = '', index = 0, staggerStep = 0.09, ...rest }) {
  return (
    <motion.div
      className={className}
      variants={{
        hidden: { opacity: 0, y: 24 },
        show: {
          opacity: 1,
          y: 0,
          transition: { duration: 0.55, delay: index * staggerStep, ease: [0.16, 1, 0.3, 1] },
        },
      }}
      {...rest}
    >
      {children}
    </motion.div>
  );
}
