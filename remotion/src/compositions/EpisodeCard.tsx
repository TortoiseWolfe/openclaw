import {
	AbsoluteFill,
	interpolate,
	spring,
	useCurrentFrame,
	useVideoConfig,
} from "remotion";
import { type Brand, getTheme, layout } from "../lib/theme";

type Props = {
	brand?: Brand;
	title: string;
	date: string;
	time: string;
	topic: string;
};

export const EpisodeCard: React.FC<Props> = ({
	brand = "turtlewolfe",
	title,
	date,
	time,
	topic,
}) => {
	const frame = useCurrentFrame();
	const { fps } = useVideoConfig();
	const { colors, fonts, effects, branding } = getTheme(brand);

	const titleOpacity = interpolate(frame, [0, 20], [0, 1], {
		extrapolateLeft: "clamp",
		extrapolateRight: "clamp",
	});
	const titleY = spring({ frame, fps, config: { damping: 14 } });

	const topicProgress = spring({
		frame: frame - 20,
		fps,
		config: { damping: 12 },
	});

	const badgeOpacity = interpolate(frame, [30, 50], [0, 1], {
		extrapolateLeft: "clamp",
		extrapolateRight: "clamp",
	});

	const lineWidth = interpolate(frame, [5, 40], [0, 600], {
		extrapolateLeft: "clamp",
		extrapolateRight: "clamp",
	});

	// Decorative corner bracket animation
	const cornerOpacity = interpolate(frame, [40, 65], [0, 0.25], {
		extrapolateLeft: "clamp",
		extrapolateRight: "clamp",
	});

	return (
		<AbsoluteFill
			style={{
				background: effects.bgGradient,
				padding: layout.padding,
				fontFamily: fonts.heading,
				display: "flex",
				flexDirection: "column",
				justifyContent: "center",
			}}
		>
			{/* Decorative corner bracket — top right */}
			<div
				style={{
					position: "absolute",
					top: 48,
					right: 48,
					width: 80,
					height: 80,
					borderTop: `2px solid ${colors.accent}`,
					borderRight: `2px solid ${colors.accent}`,
					opacity: cornerOpacity,
				}}
			/>
			{/* Decorative corner bracket — bottom left */}
			<div
				style={{
					position: "absolute",
					bottom: 48,
					left: 48,
					width: 80,
					height: 80,
					borderBottom: `2px solid ${colors.accent}`,
					borderLeft: `2px solid ${colors.accent}`,
					opacity: cornerOpacity,
				}}
			/>

			{/* Accent line with glow */}
			<div
				style={{
					width: lineWidth,
					height: 6,
					backgroundColor: colors.accent,
					marginBottom: 40,
					borderRadius: 3,
					boxShadow: effects.accentGlow,
				}}
			/>

			{/* Title */}
			<div
				style={{
					opacity: titleOpacity,
					transform: `translateY(${interpolate(titleY, [0, 1], [30, 0])}px)`,
					fontSize: 84,
					fontWeight: 800,
					color: colors.accent,
					lineHeight: 1.1,
					textShadow: effects.accentTextShadow,
					letterSpacing: -1,
				}}
			>
				{title}
			</div>

			{/* Topic */}
			<div
				style={{
					transform: `translateY(${interpolate(topicProgress, [0, 1], [40, 0])}px)`,
					opacity: topicProgress,
					fontSize: 42,
					color: colors.text,
					marginTop: 24,
					fontWeight: 300,
					fontStyle: "italic",
					letterSpacing: 0.5,
				}}
			>
				{topic}
			</div>

			{/* Date/time badge */}
			<div
				style={{
					position: "absolute",
					bottom: layout.padding,
					left: layout.padding,
					opacity: badgeOpacity,
					display: "flex",
					alignItems: "center",
					gap: 16,
				}}
			>
				<div
					style={{
						fontSize: 32,
						color: colors.bg,
						backgroundColor: colors.accent,
						padding: "14px 28px",
						borderRadius: 12,
						fontWeight: 700,
						fontFamily: fonts.mono,
						boxShadow: effects.cardShadow,
						letterSpacing: 1,
					}}
				>
					{date}
				</div>
				<div
					style={{
						fontSize: 28,
						color: colors.textMuted,
						fontFamily: fonts.mono,
					}}
				>
					{time}
				</div>
			</div>

			{/* Channel name */}
			<div
				style={{
					position: "absolute",
					bottom: layout.padding,
					right: layout.padding,
					opacity: badgeOpacity,
					fontSize: 24,
					color: colors.textMuted,
					fontFamily: fonts.mono,
					letterSpacing: 1,
				}}
			>
				{branding.channel}
			</div>
		</AbsoluteFill>
	);
};
