import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { useAuth } from "../context/AuthContext";
import api from "../services/api";
import Modal from "../components/common/Modal";
import "./Profile.css";

const PROFILE_STORAGE_KEY = "nodiq_user_profile";
const PREFERENCES_STORAGE_KEY = "nodiq_user_preferences";

/**
 * Save profile data to localStorage
 */
const saveProfileToStorage = (profileData) => {
  try {
    localStorage.setItem(PROFILE_STORAGE_KEY, JSON.stringify(profileData));
  } catch (error) {
    console.error("Error saving profile to localStorage:", error);
  }
};

/**
 * Load profile data from localStorage
 */
const loadProfileFromStorage = () => {
  try {
    const saved = localStorage.getItem(PROFILE_STORAGE_KEY);
    return saved ? JSON.parse(saved) : null;
  } catch (error) {
    console.error("Error loading profile from localStorage:", error);
    return null;
  }
};

/**
 * Save preferences to localStorage
 */
const savePreferencesToStorage = (preferencesData) => {
  try {
    localStorage.setItem(PREFERENCES_STORAGE_KEY, JSON.stringify(preferencesData));
  } catch (error) {
    console.error("Error saving preferences to localStorage:", error);
  }
};

/**
 * Load preferences from localStorage
 */
const loadPreferencesFromStorage = () => {
  try {
    const saved = localStorage.getItem(PREFERENCES_STORAGE_KEY);
    return saved ? JSON.parse(saved) : null;
  } catch (error) {
    console.error("Error loading preferences from localStorage:", error);
    return null;
  }
};

/* =========================
   Animated Counter
========================= */
function AnimatedCounter({ value, duration = 1200 }) {
  const [count, setCount] = useState(0);

  useEffect(() => {
    let start = 0;
    const end = Number(value);
    const increment = end / (duration / 16);

    const timer = setInterval(() => {
      start += increment;

      if (start >= end) {
        start = end;
        clearInterval(timer);
      }

      setCount(Math.floor(start));
    }, 16);

    return () => clearInterval(timer);
  }, [value, duration]);

  return <>{count}</>;
}

/* =========================
   Section Animation
========================= */
const sectionAnimation = {
  initial: {
    opacity: 0,
    y: 20,
  },

  whileInView: {
    opacity: 1,
    y: 0,
  },

  viewport: {
    once: true,
    amount: 0.12,
  },

  transition: {
    duration: 0.45,
    ease: "easeOut",
  },
};

function Profile() {
  const navigate = useNavigate();
  const { user, updateProfile } = useAuth();

  const [profile, setProfile] = useState({
    fullName: "",
    email: "",
    organization: "D. Y. Patil College of Engineering and Technology",
    role: "Researcher / Engineer",
    country: "India",
    phone: "",
    department: "Computer Science & Engineering",
    expertise: "Metallography",
    experience: "Intermediate",
  });

  const [preferences, setPreferences] = useState({
    analysisMode: "Nodular Cast Iron",
    units: "Metric",
    reportFormat: "PDF + Excel",
    enhancement: true,
    noiseReduction: true,
    segmentation: true,
  });

  const [saved, setSaved] = useState(false);
  const [isEditing, setIsEditing] = useState(false);
  const [editChanged, setEditChanged] = useState(false);
  const [usage, setUsage] = useState(null);

  /* ---- Change password (Account & Security section) ---- */
  const [pwOpen, setPwOpen] = useState(false);
  const [pwForm, setPwForm] = useState({
    current: "",
    next: "",
    confirm: "",
  });
  const [pwError, setPwError] = useState("");
  const [pwStatus, setPwStatus] = useState("idle"); // idle | saving | ok | error

  const openPasswordModal = () => {
    setPwForm({ current: "", next: "", confirm: "" });
    setPwError("");
    setPwStatus("idle");
    setPwOpen(true);
  };

  const submitPasswordChange = async (e) => {
    e.preventDefault();
    setPwError("");

    if (!pwForm.current || !pwForm.next || !pwForm.confirm) {
      setPwError("All fields are required.");
      return;
    }
    if (pwForm.next.length < 6) {
      setPwError("New password must be at least 6 characters.");
      return;
    }
    if (pwForm.next !== pwForm.confirm) {
      setPwError("New password and confirmation do not match.");
      return;
    }
    if (pwForm.next === pwForm.current) {
      setPwError("New password must differ from the current password.");
      return;
    }

    setPwStatus("saving");
    try {
      await api.changePassword({
        currentPassword: pwForm.current,
        newPassword: pwForm.next,
      });
      setPwStatus("ok");
      setPwForm({ current: "", next: "", confirm: "" });
      setTimeout(() => {
        setPwOpen(false);
        setPwStatus("idle");
      }, 1600);
    } catch (err) {
      setPwStatus("error");
      setPwError(err.message || "Could not change the password. Try again.");
    }
  };

  // Real usage from the server (replaces the former hard-coded numbers).
  useEffect(() => {
    let alive = true;
    Promise.all([api.analysisStats(), api.reports()])
      .then(([stats, reps]) => {
        if (!alive) return;
        const reportCount = Array.isArray(reps)
          ? reps.length
          : (reps.reports || []).length;
        const last = stats?.last_analysis_at ?
          new Date(stats.last_analysis_at).toLocaleDateString("en-IN", {
            day: "2-digit", month: "short",
          })
          : null;
        setUsage({
          analyses: stats?.total_analyses ?? 0,
          images: stats?.images_processed ?? 0,
          reports: reportCount,
          last: last || (stats?.total_analyses ? "—" : "No analyses yet"),
        });
      })
      .catch(() => {
        if (alive) setUsage({ analyses: 0, images: 0, reports: 0, last: "—" });
      });
    return () => {
      alive = false;
    };
  }, []);

  // Load user data from auth context and localStorage on component mount
  useEffect(() => {
    // First, load from localStorage if available
    const savedProfile = loadProfileFromStorage();
    const savedPreferences = loadPreferencesFromStorage();

    if (savedProfile) {
      setProfile(savedProfile);
    }

    if (savedPreferences) {
      setPreferences(savedPreferences);
    }

    // Then merge with current user data from auth context
    if (user) {
      setProfile((current) => ({
        ...current,
        fullName: user.name || user.fullName || current.fullName,
        email: user.email || current.email,
        phone: user.phone || current.phone,
      }));
    }
  }, [user]);

  /**
   * Extract initials from full name
   */
  const getInitials = (name) => {
    if (!name) return "U";
    const parts = name.trim().split(" ");
    if (parts.length >= 2) {
      return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
    }
    return parts[0].substring(0, 2).toUpperCase();
  };

  const updateProfileField = (field, value) => {
    setProfile((current) => ({
      ...current,
      [field]: value,
    }));

    setSaved(false);
    setEditChanged(true);
  };

  const updatePreference = (field, value) => {
    setPreferences((current) => ({
      ...current,
      [field]: value,
    }));
  };

  const handleSave = () => {
    // Save profile to auth context and localStorage
    updateProfile({
      ...profile,
      preferences,
    });

    // Save profile and preferences to localStorage for persistence across page refreshes
    saveProfileToStorage(profile);
    savePreferencesToStorage(preferences);

    setSaved(true);
    setEditChanged(false);
    setIsEditing(false);

    // Show success message for 2 seconds
    setTimeout(() => setSaved(false), 2000);
  };

  const handleEditToggle = () => {
    if (isEditing && editChanged) {
      // If editing and changes were made, confirm before closing
      const confirm = window.confirm(
        "You have unsaved changes. Do you want to save them before closing edit mode?"
      );
      if (confirm) {
        handleSave();
      }
      setIsEditing(false);
    } else {
      setIsEditing(!isEditing);
      setEditChanged(false);
    }
  };

  return (
    <div className="profile-page">
      {/* Ambient Background */}
      <div className="profile-background-glow profile-glow-one" />
      <div className="profile-background-glow profile-glow-two" />

      {/* Header */}
      <header className="profile-header">
        <button
          type="button"
          className="profile-back-button"
          onClick={() => navigate("/home")}
        >
          <span className="material-symbols-outlined">arrow_back</span>
          Back to Home
        </button>

        <div className="profile-brand">NODIQ-X</div>
      </header>

      <main className="profile-container">
        {/* Page heading */}
        <motion.section
          className="profile-page-heading"
          initial={{ opacity: 0, y: 15 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5 }}
        >
          <div>
            <span className="profile-eyebrow">ACCOUNT</span>
            <h1>Profile</h1>
            <p>
              Manage your personal information, professional profile, and
              NODIQ-X preferences.
            </p>
          </div>
        </motion.section>

        {/* Identity */}
        <motion.section
          className="profile-identity"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{
            duration: 0.55,
            delay: 0.1,
          }}
        >
          <div className="profile-avatar-wrapper">

            <div className="profile-avatar">
              <span>{getInitials(profile.fullName)}</span>
            </div>

            <span className="avatar-status" />

          </div>

          <div className="profile-identity-info">
            <h2>{profile.fullName || "User"}</h2>
            <p>{profile.email}</p>

            <div className="profile-meta">
              <span>{profile.role}</span>
              <span className="profile-status">
                <span className="status-dot" />
                Active Account
              </span>
            </div>
          </div>

          {/* Primary CTA of the header (audit issue 12) — solid, not ghost */}
          <button
            type="button"
            className="profile-primary-button"
            onClick={handleEditToggle}
          >
            <span className="material-symbols-outlined">edit</span>
            {isEditing ? "Cancel Edit" : "Edit Public Profile"}
          </button>
        </motion.section>

        {/* Usage */}
        <motion.section
          className="profile-metrics"
          {...sectionAnimation}
        >
          <div className="profile-metric">
            <span>Total Analyses</span>
            <strong>
              <AnimatedCounter value={usage ? usage.analyses : 0} />
            </strong>
          </div>

          <div className="profile-metric">
            <span>Images Processed</span>
            <strong>
              <AnimatedCounter value={usage ? usage.images : 0} />
            </strong>
          </div>

          <div className="profile-metric">
            <span>Reports Generated</span>
            <strong>
              <AnimatedCounter value={usage ? usage.reports : 0} />
            </strong>
          </div>

          <div className="profile-metric">
            <span>Last Analysis</span>
            <strong className="metric-text">{usage ? usage.last : "…"}</strong>
          </div>
        </motion.section>

        {/* Personal Information */}
        <motion.section
          className="profile-section"
          id="personal-information"
          {...sectionAnimation}
        >
          <div className="profile-section-heading">
            <div>
              <h2>Personal Information</h2>
              <p>
                Update the information associated with your NODIQ-X account.
              </p>
            </div>
          </div>

          <div className="profile-form-grid">
            <ProfileInput
              label="Full Name"
              value={profile.fullName}
              onChange={(value) => updateProfileField("fullName", value)}
              disabled={!isEditing}
            />

            <ProfileInput
              label="Email Address"
              value={profile.email}
              type="email"
              onChange={(value) => updateProfileField("email", value)}
              disabled={true}
            />

            <ProfileInput
              label="Organization"
              value={profile.organization}
              onChange={(value) => updateProfileField("organization", value)}
              disabled={!isEditing}
            />

            <ProfileInput
              label="Role"
              value={profile.role}
              onChange={(value) => updateProfileField("role", value)}
              disabled={!isEditing}
            />

            <ProfileInput
              label="Country"
              value={profile.country}
              onChange={(value) => updateProfileField("country", value)}
              disabled={!isEditing}
            />

            <ProfileInput
              label="Phone Number"
              value={profile.phone}
              placeholder="Add phone number"
              onChange={(value) => updateProfileField("phone", value)}
              disabled={!isEditing}
            />
          </div>
        </motion.section>

        {/* Professional Profile */}
        <motion.section
          className="profile-section"
          {...sectionAnimation}
        >
          <div className="profile-section-heading">
            <div>
              <h2>Professional Profile</h2>
              <p>
                Tell NODIQ-X about your professional background and expertise.
              </p>
            </div>
          </div>

          <div className="profile-form-grid">
            <ProfileInput
              label="Department"
              value={profile.department}
              onChange={(value) => updateProfileField("department", value)}
              disabled={!isEditing}
            />

            <ProfileInput
              label="Area of Expertise"
              value={profile.expertise}
              onChange={(value) => updateProfileField("expertise", value)}
              disabled={!isEditing}
            />

            <div className="profile-field">
              <label>Experience Level</label>
              <select
                value={profile.experience}
                onChange={(event) =>
                  updateProfileField("experience", event.target.value)
                }
                disabled={!isEditing}
              >
                <option>Beginner</option>
                <option>Intermediate</option>
                <option>Advanced</option>
                <option>Expert</option>
              </select>
            </div>
          </div>
        </motion.section>

        {/* Analysis Preferences */}
        <motion.section
          className="profile-section"
          {...sectionAnimation}
        >
          <div className="profile-section-heading">
            <div>
              <h2>Analysis Preferences</h2>
              <p>
                Customize how NODIQ-X prepares and presents your analysis
                workflow.
              </p>
            </div>
          </div>

          <div className="profile-form-grid">
            <ProfileSelect
              label="Default Analysis Mode"
              value={preferences.analysisMode}
              options={["Nodular Cast Iron", "General Microstructure"]}
              onChange={(value) =>
                updatePreference("analysisMode", value)
              }
              disabled={!isEditing}
            />

            <ProfileSelect
              label="Measurement Units"
              value={preferences.units}
              options={["Metric", "Imperial"]}
              onChange={(value) => updatePreference("units", value)}
              disabled={!isEditing}
            />

            <ProfileSelect
              label="Report Format"
              value={preferences.reportFormat}
              options={["PDF", "Excel", "PDF + Excel"]}
              onChange={(value) =>
                updatePreference("reportFormat", value)
              }
              disabled={!isEditing}
            />
          </div>

          <div className="profile-toggle-list">
            <PreferenceToggle
              label="Automatic Image Enhancement"
              description="Improve image quality before analysis."
              checked={preferences.enhancement}
              onChange={(value) =>
                updatePreference("enhancement", value)
              }
              disabled={!isEditing}
            />

            <PreferenceToggle
              label="Automatic Noise Reduction"
              description="Reduce unwanted image noise during processing."
              checked={preferences.noiseReduction}
              onChange={(value) =>
                updatePreference("noiseReduction", value)
              }
              disabled={!isEditing}
            />

            <PreferenceToggle
              label="Segmentation Assistance"
              description="Allow NODIQ-X to assist with microstructure segmentation."
              checked={preferences.segmentation}
              onChange={(value) =>
                updatePreference("segmentation", value)
              }
              disabled={!isEditing}
            />
          </div>
        </motion.section>

        {/* Save */}
        {isEditing && (
          <motion.div
            className="profile-save-row"
            {...sectionAnimation}
          >
            {saved && (
              <motion.span
                className="profile-save-message"
                initial={{
                  opacity: 0,
                  x: 10,
                }}
                animate={{
                  opacity: 1,
                  x: 0,
                }}
              >
                <span className="material-symbols-outlined">check_circle</span>
                Changes saved successfully
              </motion.span>
            )}

            <button
              type="button"
              className="profile-primary-button"
              onClick={handleSave}
              disabled={!editChanged}
            >
              <span className="material-symbols-outlined">save</span>
              Save Changes
            </button>
          </motion.div>
        )}

        {/* Security */}
        <motion.section
          className="profile-section"
          {...sectionAnimation}
        >
          <div className="profile-section-heading">
            <div>
              <h2>Account & Security</h2>
              <p>Manage your account security and access.</p>
            </div>
          </div>

          <div className="profile-security-row">
            <div>
              <span className="security-label">Password</span>
              <span className="security-value">••••••••••••</span>
            </div>

            <button
              type="button"
              className="profile-outline-button"
              onClick={openPasswordModal}
            >
              Change Password
            </button>
          </div>

          <div className="profile-security-row">
            <div>
              <span className="security-label">Account Status</span>
              <span className="security-value security-active">
                <span className="status-dot" />
                Active
              </span>
            </div>
          </div>

          {/* Session action gets its own row — it is not the "action" for
              Account Status (audit issue 18) */}
          <div className="profile-security-row profile-security-row--action">
            <div>
              <span className="security-label">Session</span>
              <span className="security-value">Signed in on this device</span>
            </div>

            <button
              type="button"
              className="profile-outline-button"
              onClick={() => navigate("/")}
            >
              Sign Out
            </button>
          </div>
        </motion.section>

        {/* Danger Zone */}
        <Modal open={pwOpen} onClose={() => setPwOpen(false)} title="Change Password">
          <form className="profile-pw-form" onSubmit={submitPasswordChange}>
            <label>
              <span className="profile-field-label">CURRENT PASSWORD</span>
              <input
                type="password"
                value={pwForm.current}
                onChange={(e) => setPwForm((f) => ({ ...f, current: e.target.value }))}
                placeholder="Enter your current password"
                autoComplete="current-password"
                required
              />
            </label>
            <label>
              <span className="profile-field-label">NEW PASSWORD</span>
              <input
                type="password"
                value={pwForm.next}
                onChange={(e) => setPwForm((f) => ({ ...f, next: e.target.value }))}
                placeholder="At least 6 characters"
                autoComplete="new-password"
                minLength={6}
                required
              />
            </label>
            <label>
              <span className="profile-field-label">CONFIRM NEW PASSWORD</span>
              <input
                type="password"
                value={pwForm.confirm}
                onChange={(e) => setPwForm((f) => ({ ...f, confirm: e.target.value }))}
                placeholder="Repeat the new password"
                autoComplete="new-password"
                minLength={6}
                required
              />
            </label>

            {pwError && <p className="profile-pw-error" role="alert">{pwError}</p>}
            {pwStatus === "ok" && (
              <p className="profile-pw-ok">
                <span className="material-symbols-outlined">check_circle</span>
                Password updated successfully.
              </p>
            )}

            <div className="profile-pw-actions">
              <button type="button" className="profile-outline-button" onClick={() => setPwOpen(false)}>
                Cancel
              </button>
              <button type="submit" className="profile-primary-button" disabled={pwStatus === "saving"}>
                {pwStatus === "saving" ? "Updating…" : "Update Password"}
              </button>
            </div>
          </form>
        </Modal>

        {/* Danger Zone */}
        <motion.section
          className="profile-danger-zone"
          {...sectionAnimation}
        >
          <div>
            <span className="danger-icon">
              <span className="material-symbols-outlined">warning</span>
            </span>

            <div>
              <h2>Danger Zone</h2>
              <p>
                Irreversible account actions. Please proceed carefully.
              </p>
            </div>
          </div>

          <button
            type="button"
            className="profile-danger-button"
            onClick={() => {
              const confirmed = window.confirm(
                "Are you sure you want to delete your NODIQ-X account?"
              );

              if (confirmed) {
                alert("Account deletion would be handled by the backend.");
              }
            }}
          >
            Delete Account
          </button>
        </motion.section>
      </main>
    </div>
  );
}

/* Reusable input */

function ProfileInput({
  label,
  value,
  onChange,
  type = "text",
  placeholder = "",
  disabled = false,
}) {
  return (
    <div className="profile-field">
      <label>{label}</label>
      <input
        type={type}
        value={value}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
        disabled={disabled}
      />
    </div>
  );
}

/* Reusable select */

function ProfileSelect({ label, value, options, onChange, disabled = false }) {
  return (
    <div className="profile-field">
      <label>{label}</label>

      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        disabled={disabled}
      >
        {options.map((option) => (
          <option key={option}>{option}</option>
        ))}
      </select>
    </div>
  );
}

/* Reusable toggle */

function PreferenceToggle({
  label,
  description,
  checked,
  onChange,
  disabled = false,
}) {
  return (
    <div className="profile-toggle">
      <div>
        <strong>{label}</strong>
        <p>{description}</p>
      </div>

      <button
        type="button"
        className={`toggle-switch ${checked ? "active" : ""}`}
        onClick={() => onChange(!checked)}
        aria-label={label}
        aria-pressed={checked}
        disabled={disabled}
      >
        <span />
      </button>
    </div>
  );
}

export default Profile;