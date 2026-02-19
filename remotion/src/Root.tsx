import { Composition } from "remotion";
import { EpisodeCard } from "./compositions/EpisodeCard";
import { EpisodeOutro } from "./compositions/EpisodeOutro";
import { StreamIntro } from "./compositions/StreamIntro";
import { HoldingScreen } from "./compositions/HoldingScreen";
import { HighlightTitle } from "./compositions/HighlightTitle";
import {
	NarratedSegment,
	calculateNarratedSegmentMetadata,
} from "./compositions/NarratedSegment";

export const RemotionRoot: React.FC = () => {
	return (
		<>
			{/* ── TurtleWolfe ── */}
			<Composition
				id="EpisodeCard"
				component={EpisodeCard}
				durationInFrames={150}
				fps={30}
				width={1920}
				height={1080}
				defaultProps={{
					brand: "turtlewolfe" as const,
					title: "Docker Basics",
					date: "2026-02-10",
					time: "8:00 PM ET",
					topic: "Building containers from scratch",
				}}
			/>
			<Composition
				id="StreamIntro"
				component={StreamIntro}
				durationInFrames={300}
				fps={30}
				width={1920}
				height={1080}
				defaultProps={{
					brand: "turtlewolfe" as const,
					episodeTitle: "Live Coding Session",
				}}
			/>
			<Composition
				id="HoldingScreen"
				component={HoldingScreen}
				durationInFrames={900}
				fps={30}
				width={1920}
				height={1080}
				defaultProps={{
					brand: "turtlewolfe" as const,
					mode: "starting-soon" as const,
					message: "Stream starts in a few minutes!",
				}}
			/>
			<Composition
				id="HighlightTitle"
				component={HighlightTitle}
				durationInFrames={90}
				fps={30}
				width={1920}
				height={1080}
				defaultProps={{
					brand: "turtlewolfe" as const,
					title: "Today's Highlights",
					date: "2026-02-04",
				}}
			/>
			<Composition
				id="EpisodeOutro"
				component={EpisodeOutro}
				durationInFrames={300}
				fps={30}
				width={1920}
				height={1080}
				defaultProps={{
					brand: "turtlewolfe" as const,
					currentEpisodeTitle: "Docker Basics",
					nextEpisodeTitle: "Kubernetes 101",
					nextEpisodeDate: "Feb 12, 2026 • 2:00 PM ET",
					nextEpisodeTopic: "Container orchestration fundamentals",
				}}
			/>

			{/* ── NarratedSegment (dynamic duration) ── */}
			<Composition
				id="NarratedSegment"
				component={NarratedSegment}
				durationInFrames={300}
				fps={30}
				width={1920}
				height={1080}
				calculateMetadata={calculateNarratedSegmentMetadata}
				defaultProps={{
					brand: "turtlewolfe" as const,
					sectionTitle: "Your First Container",
					sectionNumber: 1,
					totalSections: 4,
					bullets: [
						"docker run hello-world",
						"docker run -it ubuntu bash",
						"docker ps",
						"Key flags: -d, -p, -v",
					],
					codeBlock:
						"FROM node:22\nWORKDIR /app\nCOPY package*.json ./\nRUN npm install\nCOPY . .\nCMD [\"node\", \"index.js\"]",
					codeLanguage: "dockerfile",
					codeColumnWidth: 0,
					audioFileName: null as string | null,
					durationInFrames: 300,
					bulletTimings: [] as number[],
				}}
			/>

			{/* ── ScriptHammer NarratedSegment (dynamic duration) ── */}
			<Composition
				id="SH-NarratedSegment"
				component={NarratedSegment}
				durationInFrames={300}
				fps={30}
				width={1920}
				height={1080}
				calculateMetadata={calculateNarratedSegmentMetadata}
				defaultProps={{
					brand: "scripthammer" as const,
					sectionTitle: "Getting Started",
					sectionNumber: 1,
					totalSections: 4,
					bullets: [
						"Install dependencies",
						"Configure your environment",
						"Run the dev server",
					],
					codeBlock: null as string | null,
					codeLanguage: null as string | null,
					codeColumnWidth: 0,
					audioFileName: null as string | null,
					durationInFrames: 300,
					bulletTimings: [] as number[],
				}}
			/>

			{/* ── ScriptHammer ── */}
			<Composition
				id="SH-EpisodeCard"
				component={EpisodeCard}
				durationInFrames={150}
				fps={30}
				width={1920}
				height={1080}
				defaultProps={{
					brand: "scripthammer" as const,
					title: "SaaS Feature Demo",
					date: "2026-02-12",
					time: "7:00 PM ET",
					topic: "Auth, payments, and AI orchestration",
				}}
			/>
			<Composition
				id="SH-StreamIntro"
				component={StreamIntro}
				durationInFrames={300}
				fps={30}
				width={1920}
				height={1080}
				defaultProps={{
					brand: "scripthammer" as const,
					episodeTitle: "Building in Public",
				}}
			/>
			<Composition
				id="SH-HoldingScreen"
				component={HoldingScreen}
				durationInFrames={900}
				fps={30}
				width={1920}
				height={1080}
				defaultProps={{
					brand: "scripthammer" as const,
					mode: "starting-soon" as const,
					message: "Firing up the forge...",
				}}
			/>
			<Composition
				id="SH-HighlightTitle"
				component={HighlightTitle}
				durationInFrames={90}
				fps={30}
				width={1920}
				height={1080}
				defaultProps={{
					brand: "scripthammer" as const,
					title: "Feature Highlights",
					date: "2026-02-04",
				}}
			/>
			<Composition
				id="SH-EpisodeOutro"
				component={EpisodeOutro}
				durationInFrames={300}
				fps={30}
				width={1920}
				height={1080}
				defaultProps={{
					brand: "scripthammer" as const,
					currentEpisodeTitle: "Python for Beginners",
					nextEpisodeTitle: "React Hooks 101",
					nextEpisodeDate: "Feb 10, 2026 • 2:00 PM ET",
					nextEpisodeTopic: "Modern React state management",
				}}
			/>
		</>
	);
};
