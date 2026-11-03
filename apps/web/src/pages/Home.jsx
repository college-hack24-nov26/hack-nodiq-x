import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import SectionReveal from "../components/layout/SectionReveal";
import BinaryOrbits from "../components/animations/BinaryOrbits";
import SpecularButton from "../components/common/SpecularButton";
import './Home.css'

const pipelineStages = [
  {
    number: "01",
    title: "SEE",
    description: "Ingest high-resolution micrographs.",
    icon: "visibility",
  },
  {
    number: "02",
    title: "DETECT",
    description: "Isolate phases & inclusions.",
    icon: "center_focus_strong",
  },
  {
    number: "03",
    title: "MEASURE",
    description: "Quantify size and distribution.",
    icon: "straighten",
  },
  {
    number: "04",
    title: "UNDERSTAND",
    description: "Classify anomaly severity.",
    icon: "psychology",
  },
  {
    number: "05",
    title: "VERIFY",
    description: "Human-in-the-loop review.",
    icon: "fact_check",
  },
  {
    number: "06",
    title: "DOCUMENT",
    description: "Generate engineering reports.",
    icon: "article",
  },
];

const capabilities = [
  {
    icon: "visibility",
    label: "AI Vision",
    title: "See What Matters",
    description:
      "Automated detection of phases, grains, and inclusions with pixel-level precision.",
    type: "vision",
  },
  {
    icon: "straighten",
    label: "Quantitative",
    title: "Turn Images Into Measurements",
    description:
      "Extract grain sizing, distribution and quantitative measurements from micrographs.",
    type: "measurement",
  },
  {
    icon: "category",
    label: "Morphology",
    title: "Understand Structure",
    description:
      "Classify complex shapes and orientations to understand material behavior.",
    type: "morphology",
  },
  {
    icon: "warning",
    label: "Anomalies",
    title: "Find What Looks Different",
    description:
      "Identify rare defects and outliers that traditional algorithms can miss.",
    type: "anomaly",
  },
  {
    icon: "psychology",
    label: "Explainable AI",
    title: "Ask Why",
    description:
      "Trace AI decisions back to the pixels and features that triggered them.",
    type: "explainable",
  },
  {
    icon: "verified_user",
    label: "Verification",
    title: "Keep Engineers In Control",
    description:
      "Combine AI speed with human expertise before final sign-off.",
    type: "verification",
  },
];

const workflowStages = [
  {
    number: "01",
    title: "CAPTURE",
    heading: "Start With the Microstructure",
    description:
      "Ingest raw metallographic images directly from the microscope.",
    icon: "photo_camera",
  },
  {
    number: "02",
    title: "ANALYZE",
    heading: "Apply AI-Assisted Vision",
    description:
      "Automatically identify phases, grains and structural boundaries.",
    icon: "auto_awesome",
  },
  {
    number: "03",
    title: "MEASURE",
    heading: "Extract Quantitative Information",
    description:
      "Convert visual data into measurable engineering information.",
    icon: "straighten",
  },
  {
    number: "04",
    title: "INVESTIGATE",
    heading: "Understand What Data Reveals",
    description:
      "Highlight anomalies and regions requiring expert attention.",
    icon: "search",
  },
  {
    number: "05",
    title: "VERIFY",
    heading: "Engineer Reviews Findings",
    description:
      "Human-in-the-loop confirmation of critical AI decisions.",
    icon: "fact_check",
  },
  {
    number: "06",
    title: "DOCUMENT",
    heading: "Create Engineering Result",
    description:
      "Generate final reports and exportable engineering datasets.",
    icon: "description",
  },
];

function HeroVisual() {
  return (
    <div className="hero-visual">
      <div className="hero-window">
        <div className="hero-window-bar">
          <div className="window-status">
            <span className="status-dot status-red" />
            <span className="status-dot status-green" />

            <span className="technical-text">
              MICROSTRUCTURE_SCAN_04.TIF
            </span>
          </div>

          <span className="material-symbols-outlined">
            fullscreen
          </span>
        </div>

        <div className="microstructure-image">
          <BinaryOrbits
            colors={["#FF7A18", "#FFD8A8"]}
            backgroundColor="#101416"
            stars={85000}
            starSize={1.6}
            sparkle={0.6}
            arms={3}
            twist={3.5}
            armStrength={0.55}
            dust={0.4}
            core={1.2}
            coreSize={0.08}
            tilt={58}
            roll={-10}
            scale={1.1}
            speed={0.8}
            twinkle={0.4}
            depth={0.45}
            glow={0.65}
            intensity={1.2}
            interactive={true}
            hoverWake={true}
            clickRipple={true}
            className="microstructure-orbits-bg"
          />

          <div className="scan-line" />

          <div className="analysis-box box-one">
            <span>PHASE_A</span>
          </div>

          <div className="analysis-box box-two">
            <span>INCLUSION</span>
          </div>

          <div className="measurement-line">
            <span>12.45 μm</span>
          </div>

          <div className="hud-point point-one" />
          <div className="hud-point point-two" />
          <div className="hud-point point-three" />

          <div className="microstructure-noise" />
        </div>
      </div>
    </div>
  );
}

function Hero() {
  const navigate = useNavigate();
  return (
    <section className="hero-section" id="hero">
      <div className="engineering-grid" />

      <div className="hero-content">
        <SectionReveal animation="fade-right">
          <div className="hero-copy">
            <span className="technical-label">
              NODIQ-X
            </span>

            <h1>
              Turn Microstructure Into{" "}
              <span>Engineering Intelligence.</span>
            </h1>

            <p>
              Advanced computer vision meets industrial metallurgy.
              Automate defect detection, grain sizing, inclusion
              analysis and engineering verification with rigorous
              precision.
            </p>

            <div className="hero-actions">
              <SpecularButton
                size="lg"
                radius={18}
                tint="#18181b"
                tintOpacity={1}
                textColor="#ffffff"
                lineColor="#f97316"
                baseColor="#ffffff"
                intensity={1}
                idleIntensity={0.35}
                shineSize={10}
                shineFade={34}
                thickness={1.2}
                glow={1}
                followMouse
                proximity={250}
                className="home-specular-primary"
                onClick={() => navigate('/new-analysis')}
              >
                + Start New Analysis
              </SpecularButton>

              <SpecularButton
                size="lg"
                radius={18}
                tint="#18181b"
                tintOpacity={1}
                textColor="#ffffff"
                lineColor="#f97316"
                baseColor="#ffffff"
                intensity={1}
                idleIntensity={0.35}
                shineSize={10}
                shineFade={34}
                thickness={1.2}
                glow={1}
                followMouse
                proximity={250}
                variant="secondary"
                className="home-specular-secondary"
                onClick={() => navigate('/dashboard')}
              >
                Explore Dashboard
              </SpecularButton>
            </div>
          </div>
        </SectionReveal>

        <SectionReveal animation="scale-in" delay={180}>
          <HeroVisual />
        </SectionReveal>
      </div>
    </section>
  );
}

function IntelligencePipeline() {
  return (
    <section className="pipeline-section" id="pipeline">
      <div className="section-container">
        <SectionReveal animation="fade-up">
          <div className="section-heading centered">
            <span className="technical-label">
              02 / INTELLIGENCE PIPELINE
            </span>

            <h2>
              See → Detect → Measure → Understand → Verify → Document
            </h2>

            <p>
              A systematic intelligence pipeline that transforms raw
              microstructure into verified engineering information.
            </p>
          </div>
        </SectionReveal>

        <div className="pipeline-track">
          <div className="pipeline-signal" />

          {pipelineStages.map((stage, index) => (
            <SectionReveal
              key={stage.number}
              animation="pipeline-node"
              delay={index * 100}
            >
              <div className="pipeline-stage">
                <div className="pipeline-number">
                  {stage.number}
                </div>

                <div className="pipeline-icon">
                  <span className="material-symbols-outlined">
                    {stage.icon}
                  </span>
                </div>

                <h3>{stage.title}</h3>

                <p>{stage.description}</p>

                {index < pipelineStages.length - 1 && (
                  <div className="pipeline-connector">
                    <span />
                  </div>
                )}
              </div>
            </SectionReveal>
          ))}
        </div>
      </div>
    </section>
  );
}

function NodularitySection() {
  const sectionRef = useRef(null);
  const [isVisible, setIsVisible] = useState(false);

  useEffect(() => {
    const element = sectionRef.current;

    if (!element) return;

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setIsVisible(true);
          observer.unobserve(element);
        }
      },
      {
        threshold: 0.2,
      }
    );

    observer.observe(element);

    return () => observer.disconnect();
  }, []);

  return (
    <section
      ref={sectionRef}
      className={`nodularity-section ${
        isVisible ? "nodularity-section--visible" : ""
      }`}
    >
      {/* =========================
          SECTION HEADER
      ========================== */}
      <div className="nodularity-header">
        <div className="nodularity-kicker">
          <span className="nodularity-kicker-line" />
          <span>MICROSTRUCTURAL INTELLIGENCE</span>
        </div>

        <h2>
          Understanding <span>Nodularity</span>
        </h2>

        <p>
          From graphite morphology to measurable engineering insight —
          NODIQ-X transforms microstructure into structured,
          explainable data.
        </p>
      </div>

      {/* =========================
          WHAT IS NODULARITY
      ========================== */}
      <div className="nodularity-main">
        {/* LEFT CONTENT */}
        <div className="nodularity-definition">
          <div className="nodularity-number">01</div>

          <div className="nodularity-definition-content">
            <span className="nodularity-label">
              WHAT IS NODULARITY?
            </span>

            <h3>
              The geometry of graphite
              <br />
              defines performance.
            </h3>

            <p>
              Nodularity describes the degree to which graphite
              particles in nodular cast iron approach a spheroidal
              or nodular form.
            </p>

            <p>
              It is a critical indicator of microstructural quality
              because graphite morphology strongly influences the
              mechanical behavior and reliability of the material.
            </p>

            <p>
              Quantitative assessment considers graphite shape,
              nodule count, size distribution, and particle
              morphology across the analyzed field.
            </p>
          </div>
        </div>

        {/* RIGHT MICROSTRUCTURE VISUAL */}
        <div className="nodularity-visual">
          <div className="nodularity-grid" />

          <div className="microstructure-orbit orbit-one" />
          <div className="microstructure-orbit orbit-two" />

          <div className="nodule nodule-one" />
          <div className="nodule nodule-two" />
          <div className="nodule nodule-three" />
          <div className="nodule nodule-four" />
          <div className="nodule nodule-five" />

          <div className="nodularity-scan-line" />

          <div className="nodularity-data">
            <span>NODULE MORPHOLOGY</span>
            <strong>SPHEROIDAL</strong>
          </div>
        </div>
      </div>

      {/* =========================
          WHY NODIQ-X
      ========================== */}
      <div className="nodiq-advantage">
        <div className="advantage-intro">
          <div className="nodularity-number">02</div>

          <div>
            <span className="nodularity-label">
              WHY NODIQ-X?
            </span>

            <h3>
              Beyond counting.
              <br />
              <span>Understanding.</span>
            </h3>
          </div>
        </div>

        {/* PROCESS FLOW */}
        <div className="advantage-flow">
          <div className="advantage-step">
            <span>01</span>

            <strong>Detect</strong>

            <p>
              Identify graphite nodules using computer vision
              and image-processing techniques.
            </p>
          </div>

          <div className="advantage-connector">
            <span>→</span>
          </div>

          <div className="advantage-step">
            <span>02</span>

            <strong>Measure</strong>

            <p>
              Quantify nodularity, nodule density, morphology,
              and particle characteristics.
            </p>
          </div>

          <div className="advantage-connector">
            <span>→</span>
          </div>

          <div className="advantage-step">
            <span>03</span>

            <strong>Verify</strong>

            <p>
              Combine quality assessment, uncertainty estimation,
              and human review for trustworthy results.
            </p>
          </div>

          <div className="advantage-connector">
            <span>→</span>
          </div>

          <div className="advantage-step advantage-step-final">
            <span>04</span>

            <strong>Understand</strong>

            <p>
              Transform measurements into explainable engineering
              intelligence and automated documentation.
            </p>
          </div>
        </div>
      </div>

      {/* =========================
          ASTM / PLATFORM STATEMENT
      ========================== */}
      <div className="nodularity-statement">
        <div className="statement-line" />

        <p>
          Built around established metallographic analysis
          methodologies, including ASTM E2567, NODIQ-X extends
          conventional image analysis with AI-assisted
          interpretation, verification, reference comparison,
          batch analytics, uncertainty estimation, and automated
          reporting.
        </p>

        <div className="statement-line" />
      </div>
    </section>
  );
}

function CapabilityVisual({ type }) {
  if (type === "vision") {
    return (
      <div className="capability-visual vision-visual">
        <div className="vision-grid" />
        <div className="vision-target">
          <span>PHASE_A</span>
        </div>

        <div className="vision-crosshair">
          <span />
          <span />
        </div>
      </div>
    );
  }

  if (type === "measurement") {
    return (
      <div className="capability-visual measurement-visual">
        <div className="measurement-ruler">
          <span>0</span>
          <span>5</span>
          <span>10</span>
          <span>12.45 μm</span>
        </div>

        <div className="measurement-bar">
          <span />
        </div>
      </div>
    );
  }

  if (type === "morphology") {
    return (
      <div className="capability-visual morphology-visual">
        <div className="morphology-particle particle-a" />
        <div className="morphology-particle particle-b" />
        <div className="morphology-particle particle-c" />

        <div className="morphology-axis axis-x" />
        <div className="morphology-axis axis-y" />
      </div>
    );
  }

  if (type === "anomaly") {
    return (
      <div className="capability-visual anomaly-visual">
        <div className="anomaly-radar">
          <span />
          <span />
          <span />
        </div>

        <div className="anomaly-warning">
          <span className="material-symbols-outlined">
            priority_high
          </span>
        </div>

        <span className="anomaly-label">
          ANOMALY_DETECTED
        </span>
      </div>
    );
  }

  if (type === "explainable") {
    return (
      <div className="capability-visual explainable-visual">
        <div className="explain-node node-image">
          <span className="material-symbols-outlined">
            image
          </span>
        </div>

        <div className="explain-line">
          <span />
        </div>

        <div className="explain-node node-feature">
          <span className="material-symbols-outlined">
            center_focus_strong
          </span>
        </div>

        <div className="explain-line">
          <span />
        </div>

        <div className="explain-node node-result">
          <span className="material-symbols-outlined">
            psychology
          </span>
        </div>
      </div>
    );
  }

  return (
    <div className="capability-visual verification-visual">
      <div className="verification-ring">
        <span className="material-symbols-outlined">
          verified
        </span>
      </div>

      <div className="verification-stamp">
        VERIFIED
      </div>

      <div className="verification-line">
        HUMAN_SIGN_OFF
      </div>
    </div>
  );
}

function Capabilities() {
  return (
    <section className="capabilities-section" id="capabilities">
      <div className="section-container">
        <SectionReveal animation="fade-up">
          <div className="section-heading">
            <span className="technical-label">
              03 / CAPABILITIES
            </span>

            <h2>What NODIQ-X Can Do</h2>

            <p>
              Connect computer vision, quantitative analysis,
              AI intelligence and engineering verification into
              one industrial intelligence system.
            </p>
          </div>
        </SectionReveal>

        <div className="capability-grid">
          {capabilities.map((capability, index) => (
            <SectionReveal
              key={capability.label}
              animation="capability-reveal"
              delay={index * 80}
            >
              <article className="capability-module">
                <div className="capability-header">
                  <div className="capability-icon">
                    <span className="material-symbols-outlined">
                      {capability.icon}
                    </span>
                  </div>

                  <span className="technical-label">
                    {capability.label}
                  </span>
                </div>

                <h3>{capability.title}</h3>

                <p>{capability.description}</p>

                <CapabilityVisual type={capability.type} />
              </article>
            </SectionReveal>
          ))}
        </div>
      </div>
    </section>
  );
}

function AIHuman() {
  return (
    <section className="ai-human-section" id="ai-human">
      <div className="section-container">
        <SectionReveal animation="fade-up">
          <div className="section-heading centered">
            <span className="technical-label">
              04 / AI + HUMAN
            </span>

            <h2>
              AI → Engineer Review → Verified Result
            </h2>

            <p>
              AI accelerates the investigation. Engineers retain
              control over the final engineering decision.
            </p>
          </div>
        </SectionReveal>

        <div className="ai-human-flow">
          <SectionReveal animation="slide-left">
            <div className="intelligence-node ai-node">
              <div className="node-header">
                <span className="material-symbols-outlined">
                  analytics
                </span>

                <span className="technical-label">
                  AI INTELLIGENCE
                </span>
              </div>

              <div className="ai-scanner">
                <div className="scanner-grid" />
                <div className="scanner-frame" />
                <div className="scanner-beam" />

                <span className="scanner-tag">
                  DETECTING
                </span>
              </div>

              <div className="ai-actions">
                <span>DETECT</span>
                <span>MEASURE</span>
                <span>CLASSIFY</span>
                <span>COMPARE</span>
                <span>FLAG</span>
                <span>EXPLAIN</span>
              </div>
            </div>
          </SectionReveal>

          <div className="flow-arrow">
            <div className="flow-particle" />

            <span className="material-symbols-outlined">
              arrow_forward
            </span>
          </div>

          <SectionReveal animation="scale-in" delay={150}>
            <div className="intelligence-node engineer-node">
              <div className="node-header">
                <span className="material-symbols-outlined">
                  engineering
                </span>

                <span className="technical-label">
                  ENGINEER REVIEW
                </span>
              </div>

              <div className="review-interface">
                <div className="review-item">
                  <span className="material-symbols-outlined">
                    search
                  </span>

                  <span>Inspect Microstructure</span>
                </div>

                <div className="review-item">
                  <span className="material-symbols-outlined">
                    edit_note
                  </span>

                  <span>Correct Annotations</span>
                </div>

                <div className="review-item review-approved">
                  <span className="material-symbols-outlined">
                    check_circle
                  </span>

                  <span>Validate Results</span>
                </div>
              </div>

              <div className="human-status">
                HUMAN_IN_THE_LOOP_ACTIVE
              </div>
            </div>
          </SectionReveal>

          <div className="flow-arrow">
            <div className="flow-particle flow-particle-green" />

            <span className="material-symbols-outlined">
              arrow_forward
            </span>
          </div>

          <SectionReveal animation="slide-right" delay={300}>
            <div className="intelligence-node verified-node">
              <div className="node-header">
                <span className="material-symbols-outlined">
                  verified
                </span>

                <span className="technical-label">
                  VERIFIED RESULT
                </span>
              </div>

              <div className="verified-content">
                <div className="verified-icon">
                  <span className="material-symbols-outlined">
                    task_alt
                  </span>
                </div>

                <div className="verified-badge">
                  VERIFIED
                </div>

                <p>
                  Final analysis locked and ready for
                  engineering documentation.
                </p>
              </div>

              <div className="verified-footer">
                <span>NODIQ-X / RESULT_082</span>

                <span className="material-symbols-outlined">
                  download
                </span>
              </div>
            </div>
          </SectionReveal>
        </div>
      </div>
    </section>
  );
}

function WorkflowVisual({ stage }) {
  if (stage === 0) {
    return (
      <div className="workflow-visual capture-visual">
        <div className="capture-aperture">
          <span />
        </div>

        <div className="capture-corner top-left" />
        <div className="capture-corner bottom-right" />
      </div>
    );
  }

  if (stage === 1) {
    return (
      <div className="workflow-visual analyze-visual">
        <div className="analyze-scan" />
        <div className="analyze-box">
          <span>DETECTING...</span>
        </div>
      </div>
    );
  }

  if (stage === 2) {
    return (
      <div className="workflow-visual measure-workflow">
        <div className="workflow-ruler">
          <span />
          <span />
        </div>

        <div className="workflow-value">
          12.45 μm
        </div>
      </div>
    );
  }

  if (stage === 3) {
    return (
      <div className="workflow-visual investigate-visual">
        <div className="investigate-wave" />

        <div className="investigate-alert">
          <span className="material-symbols-outlined">
            priority_high
          </span>
        </div>
      </div>
    );
  }

  if (stage === 4) {
    return (
      <div className="workflow-visual verify-workflow">
        <span className="technical-text">
          AI_FINDING
        </span>

        <span className="material-symbols-outlined">
          arrow_downward
        </span>

        <div className="validated">
          VALIDATED
        </div>
      </div>
    );
  }

  return (
    <div className="workflow-visual document-visual">
      <div className="document-line long" />
      <div className="document-line medium" />
      <div className="document-line short" />

      <div className="document-verified">
        <span className="material-symbols-outlined">
          verified
        </span>
      </div>
    </div>
  );
}

function FullWorkflow() {
  return (
    <section className="workflow-section" id="workflow">
      <div className="section-container">
        <SectionReveal animation="fade-up">
          <div className="section-heading centered">
            <span className="technical-label">
              05 / FULL WORKFLOW
            </span>

            <h2>
              Image → Analysis → Measurement → Investigation
              → Verification → Documentation
            </h2>

            <p>
              One continuous intelligence pipeline from raw
              microstructure to verified engineering information.
            </p>
          </div>
        </SectionReveal>

        <div className="workflow-timeline">
          <div className="workflow-line">
            <span />
          </div>

          {workflowStages.map((stage, index) => (
            <SectionReveal
              key={stage.number}
              animation={
                index % 2 === 0
                  ? "workflow-left"
                  : "workflow-right"
              }
              delay={index * 70}
            >
              <article className="workflow-stage">
                <div className="workflow-marker">
                  {stage.number}
                </div>

                <div className="workflow-content">
                  <div className="workflow-title">
                    <span className="technical-label">
                      {stage.title}
                    </span>

                    <span className="material-symbols-outlined">
                      {stage.icon}
                    </span>
                  </div>

                  <h3>{stage.heading}</h3>

                  <p>{stage.description}</p>
                </div>

                <WorkflowVisual stage={index} />
              </article>
            </SectionReveal>
          ))}
        </div>
      </div>
    </section>
  );
}

function CTA() {
  const navigate = useNavigate();
  return (
    <section className="cta-section" id="cta">
      <div className="section-container">
        <SectionReveal animation="scale-in">
          <div className="cta-card">
            <div className="cta-grid" />

            <div className="cta-content">
              <span className="technical-label">
                06 / READY FOR ANALYSIS
              </span>

              <h2>
                Ready to See What Your Microstructure Reveals?
              </h2>

              <p>
                Upload a microstructure image and begin your
                first AI-assisted engineering analysis.
              </p>

              <div className="cta-actions">
                <SpecularButton
                  size="lg"
                  radius={18}
                  tint="#18181b"
                  tintOpacity={1}
                  textColor="#ffffff"
                  lineColor="#f97316"
                  baseColor="#ffffff"
                  intensity={1}
                  idleIntensity={0.35}
                  shineSize={10}
                  shineFade={34}
                  thickness={1.2}
                  glow={1}
                  followMouse
                  proximity={250}
                  className="home-specular-primary"
                  onClick={() => navigate('/new-analysis')}
                >
                  + START ANALYSIS
                </SpecularButton>

                <SpecularButton
                  size="lg"
                  radius={18}
                  tint="#18181b"
                  tintOpacity={1}
                  textColor="#ffffff"
                  lineColor="#f97316"
                  baseColor="#ffffff"
                  intensity={1}
                  idleIntensity={0.35}
                  shineSize={10}
                  shineFade={34}
                  thickness={1.2}
                  glow={1}
                  followMouse
                  proximity={250}
                  variant="secondary"
                  className="home-specular-secondary"
                  onClick={() => navigate('/dashboard')}
                >
                  Go to Dashboard →
                </SpecularButton>
              </div>
            </div>

            <div className="cta-visual">
              <div className="cta-orbit orbit-one" />
              <div className="cta-orbit orbit-two" />
              <div className="cta-core">
                <span className="material-symbols-outlined">
                  biotech
                </span>
              </div>

              <div className="system-status">
                SYSTEM_READY
              </div>
            </div>
          </div>
        </SectionReveal>

        <footer className="footer">
          <span>
            NODIQ-X INDUSTRIAL INTELLIGENCE © 2026
          </span>

          <div className="footer-dots">
            <span />
            <span />
            <span />
          </div>
        </footer>
      </div>
    </section>
  );
}



function Home() {
  return (
    <div className="nodq-app">
      <main className="nodq-main">
        <Hero />

        <IntelligencePipeline />

        <NodularitySection />

        <Capabilities />

        <AIHuman />

        <FullWorkflow />

        <CTA />
      </main>
    </div>
  );
}

export default Home;