import { AnimatePresence, motion } from 'framer-motion';
import './Toast.css';

/** tone: 'default' | 'success' | 'warning' | 'error' */
export default function Toast({ open, tone = 'default', message, onClose }) {
  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className={`toast toast--${tone}`}
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: 12 }}
          transition={{ duration: 0.25, ease: [0.16, 1, 0.3, 1] }}
          role="status"
        >
          <span>{message}</span>
          {onClose && <button onClick={onClose} aria-label="Dismiss">×</button>}
        </motion.div>
      )}
    </AnimatePresence>
  );
}
