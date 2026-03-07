"use client";

import { useEffect, useRef } from "react";

interface Node {
  x: number;
  y: number;
  label: string;
  tier: number;
  pulse: number;
}

// Each particle follows an explicit path through node indices,
// advancing edge-by-edge rather than jumping across connections.
interface Particle {
  x: number;
  y: number;
  path: number[];      // ordered node indices, e.g. [0, 1, 2, 4, 6, 7]
  pathIndex: number;   // current edge: path[pathIndex] → path[pathIndex+1]
  edgeProgress: number; // 0..1 within the current edge
  speed: number;
}

// node indices: 0=I1, 1=I2, 2=I3, 3=I4, 4=I5, 5=SMC, 6=I7, 7=I8
const PATHS: number[][] = [
  [0, 1, 2, 4, 6, 7], // I1 → I2 → I3 → I5 → I7 → I8
  [0, 1, 3, 5, 6, 7], // I1 → I2 → I4 → SMC → I7 → I8
  [0, 1, 2, 6, 7],    // I1 → I2 → I3 → I7 → I8 (direct)
  [0, 1, 3, 6, 7],    // I1 → I2 → I4 → I7 → I8 (direct)
];

export function PipelineAnimation() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const animationRef = useRef<number | undefined>(undefined);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const resize = () => {
      const parent = canvas.parentElement;
      if (parent) {
        canvas.width = parent.clientWidth;
        canvas.height = parent.clientHeight;
      }
    };
    resize();
    window.addEventListener("resize", resize);

    // I1→I2→(I3/I4)→(I5/SMC)→I7→I8
    const nodes: Node[] = [
      { x: 0.06, y: 0.50, label: "I1",  tier: 0, pulse: 0.0 },
      { x: 0.22, y: 0.50, label: "I2",  tier: 1, pulse: 0.4 },
      { x: 0.38, y: 0.32, label: "I3",  tier: 2, pulse: 0.5 },
      { x: 0.38, y: 0.68, label: "I4",  tier: 2, pulse: 0.3 },
      { x: 0.58, y: 0.32, label: "I5",  tier: 3, pulse: 0.7 },
      { x: 0.58, y: 0.68, label: "SMC", tier: 3, pulse: 0.6 },
      { x: 0.76, y: 0.50, label: "I7",  tier: 4, pulse: 0.4 },
      { x: 0.93, y: 0.50, label: "I8",  tier: 5, pulse: 0.2 },
    ];

    const connections: Array<[number, number]> = [
      [0, 1],           // I1 → I2
      [1, 2], [1, 3],   // I2 → I3, I4
      [2, 4], [2, 6],   // I3 → I5, I7
      [3, 5], [3, 6],   // I4 → SMC, I7
      [4, 6], [5, 6],   // I5, SMC → I7
      [6, 7],           // I7 → I8
    ];

    const particles: Particle[] = [];
    const maxParticles = 30;

    const spawnParticle = () => {
      const path = PATHS[Math.floor(Math.random() * PATHS.length)];
      particles.push({
        x: nodes[path[0]].x,
        y: nodes[path[0]].y,
        path,
        pathIndex: 0,
        edgeProgress: 0,
        speed: 0.008 + Math.random() * 0.012,
      });
    };

    const animate = () => {
      ctx.fillStyle = "#0A0E14";
      ctx.fillRect(0, 0, canvas.width, canvas.height);

      const w = canvas.width;
      const h = canvas.height;

      // Draw connections
      ctx.strokeStyle = "rgba(78, 214, 200, 0.1)";
      ctx.lineWidth = 1;
      connections.forEach(([fromIdx, toIdx]) => {
        const from = nodes[fromIdx];
        const to = nodes[toIdx];
        ctx.beginPath();
        ctx.moveTo(from.x * w, from.y * h);
        ctx.lineTo(to.x * w, to.y * h);
        ctx.stroke();
      });

      // Draw nodes
      nodes.forEach((node) => {
        node.pulse = (node.pulse + 0.02) % (Math.PI * 2);
        const x = node.x * w;
        const y = node.y * h;
        const pulseIntensity = 0.5 + Math.sin(node.pulse) * 0.5;

        const gradient = ctx.createRadialGradient(x, y, 0, x, y, 30);
        gradient.addColorStop(0, `rgba(78, 214, 200, ${0.3 * pulseIntensity})`);
        gradient.addColorStop(1, "rgba(78, 214, 200, 0)");
        ctx.fillStyle = gradient;
        ctx.beginPath();
        ctx.arc(x, y, 30, 0, Math.PI * 2);
        ctx.fill();

        ctx.fillStyle = "#4ED6C8";
        ctx.beginPath();
        ctx.arc(x, y, 6, 0, Math.PI * 2);
        ctx.fill();

        ctx.fillStyle = "rgba(228, 232, 239, 0.8)";
        ctx.font = "12px JetBrains Mono";
        ctx.textAlign = "center";
        ctx.fillText(node.label, x, y - 15);
      });

      // Spawn particles
      if (particles.length < maxParticles && Math.random() < 0.1) {
        spawnParticle();
      }

      // Update and draw particles
      for (let i = particles.length - 1; i >= 0; i--) {
        const p = particles[i];
        p.edgeProgress += p.speed;

        if (p.edgeProgress >= 1) {
          p.pathIndex++;
          if (p.pathIndex >= p.path.length - 1) {
            particles.splice(i, 1);
            continue;
          }
          p.edgeProgress -= 1;
        }

        const fromNode = nodes[p.path[p.pathIndex]];
        const toNode = nodes[p.path[p.pathIndex + 1]];

        p.x = fromNode.x + (toNode.x - fromNode.x) * p.edgeProgress;
        p.y = fromNode.y + (toNode.y - fromNode.y) * p.edgeProgress;

        ctx.fillStyle = `rgba(212, 168, 75, ${0.8 - p.edgeProgress * 0.5})`;
        ctx.beginPath();
        ctx.arc(p.x * w, p.y * h, 3, 0, Math.PI * 2);
        ctx.fill();

        ctx.strokeStyle = `rgba(212, 168, 75, ${0.4 - p.edgeProgress * 0.3})`;
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(fromNode.x * w, fromNode.y * h);
        ctx.lineTo(p.x * w, p.y * h);
        ctx.stroke();
      }

      animationRef.current = requestAnimationFrame(animate);
    };

    animate();

    return () => {
      window.removeEventListener("resize", resize);
      if (animationRef.current) {
        cancelAnimationFrame(animationRef.current);
      }
    };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      className="absolute inset-0 w-full h-full"
      style={{ background: "var(--landing-bg)" }}
    />
  );
}
