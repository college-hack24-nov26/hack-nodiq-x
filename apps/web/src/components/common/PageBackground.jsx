import React from "react";
import "./PageBackground.css";

const PageBackground = ({ children }) => {
  return (
    <div className="nodiq-page">
      <div className="nodiq-background">
        <div className="gradient-orb orb-cyan"></div>
        <div className="gradient-orb orb-violet"></div>
        <div className="gradient-orb orb-blue"></div>

        <div className="background-grid"></div>
        <div className="background-noise"></div>
      </div>

      <div className="nodiq-page-content">
        {children}
      </div>
    </div>
  );
};

export default PageBackground;