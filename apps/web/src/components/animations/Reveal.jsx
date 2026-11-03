import { motion } from 'framer-motion';

/**
 * Scroll-triggered reveal container. Wrap a grid/list of SlideUp children
 * (or any motion children using the 'show'/'hidden' variant names) to have
 * them animate in staggered sequence as the section enters the viewport.
 */
export default function Reveal({ children, className = '', once = true, amount = 0.2, stagger = 0.09, ...rest }) {
  return (
    <motion.div
      className={className}
      initial="hidden"
      whileInView="show"
      viewport={{ once, amount }}
      variants={{
        hidden: {},
        show: { transition: { staggerChildren: stagger } },
      }}
      {...rest}
    >
      {children}
    </motion.div>
  );
}
