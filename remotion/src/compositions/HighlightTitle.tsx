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
};

export const HighlightTitle: React.FC<Props> = ({
	brand = "turtlewolfe",
	title,
	date,
}) => {
	const frame = useCurrentFrame();
	const { fps } = useVideoConfig();
	const { colors, fonts, effects } = getTheme(brand);

	const barWidth = spring({ frame, fps, config: { damping: 16 } });

	const titleProgress = spring({
		frame: frame - 8,
		fps,
		config: { damping: 12 },
	});

	const dateOpacity = interpolate(frame, [20, 40], [0, 1], {
		extrapolateRight: "clamp",
		extrapolateLeft: "clamp",
	});

	const fadeOut = interpolate(frame, [70, 88], [1, 0], {
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
				opacity: fadeOut,
			}}
		>
			{/* Sliding accent bar with glow */}
			<div
				style={{
					width: interpolate(barWidth, [0, 1], [0, 400]),
					height: 6,
					background: `linear-gradient(90deg, ${colors.accent}, ${colors.accentDim})`,
					borderRadius: 3,
					marginBottom: 32,
					boxShadow: effects.accentGlow,
				}}
			/>

			{/* Title */}
			<div
				style={{
					fontSize: 80,
					fontWeight: 800,
					color: colors.text,
					transform: `translateY(${interpolate(titleProgress, [0, 1], [24, 0])}px)`,
					opacity: titleProgress,
					letterSpacing: -1,
				}}
			>
				{title}
			</div>

			{/* Date */}
			<div
				style={{
					fontSize: 28,
					color: colors.textMuted,
					marginTop: 16,
					opacity: dateOpacity,
					fontFamily: fonts.mono,
					letterSpacing: 1,
				}}
			>
				{date}
			</div>
		</AbsoluteFill>
	);
};
