import React from "react";
import {
	AbsoluteFill,
	interpolate,
	useCurrentFrame,
} from "remotion";
import { type Brand, getTheme } from "../lib/theme";

type Props = {
	brand?: Brand;
	mode: "starting-soon" | "brb";
	message: string;
};

/** Slowly drifting grid dots for visual interest while looping. */
const GridDots: React.FC<{ dotColor: string }> = ({ dotColor }) => {
	const frame = useCurrentFrame();
	const spacing = 80;
	const drift = frame * 0.3;

	const dots = React.useMemo(() => {
		const result: { x: number; y: number }[] = [];
		for (let x = -spacing; x < 1920 + spacing; x += spacing) {
			for (let y = -spacing; y < 1080 + spacing; y += spacing) {
				result.push({ x, y });
			}
		}
		return result;
	}, [spacing]);

	return (
		<>
			{dots.map(({ x, y }) => {
				const offsetX = (x + drift) % (1920 + spacing * 2) - spacing;
				const offsetY = (y + drift * 0.6) % (1080 + spacing * 2) - spacing;
				return (
					<div
						key={`${x}-${y}`}
						style={{
							position: "absolute",
							left: offsetX,
							top: offsetY,
							width: 3,
							height: 3,
							borderRadius: "50%",
							backgroundColor: dotColor,
							opacity: 0.15,
						}}
					/>
				);
			})}
		</>
	);
};

export const HoldingScreen: React.FC<Props> = ({
	brand = "turtlewolfe",
	mode,
	message,
}) => {
	const frame = useCurrentFrame();
	const { colors, fonts, effects, branding } = getTheme(brand);

	const heading =
		mode === "starting-soon" ? "Starting Soon" : "Be Right Back";

	const pulse = Math.sin(frame * 0.05) * 0.06 + 1;

	const msgOpacity = interpolate(frame, [30, 60], [0, 1], {
		extrapolateRight: "clamp",
		extrapolateLeft: "clamp",
	});

	// Divider
	const dividerWidth = interpolate(frame, [10, 50], [0, 300], {
		extrapolateLeft: "clamp",
		extrapolateRight: "clamp",
	});

	return (
		<AbsoluteFill
			style={{ background: effects.bgGradient, overflow: "hidden" }}
		>
			<GridDots dotColor={colors.codeBlue} />

			{/* Center content */}
			<div
				style={{
					position: "absolute",
					top: "50%",
					left: "50%",
					transform: `translate(-50%, -50%) scale(${pulse})`,
					textAlign: "center",
				}}
			>
				<div
					style={{
						fontSize: 72,
						fontWeight: 800,
						color: colors.accent,
						fontFamily: fonts.heading,
						marginBottom: 16,
						textShadow: effects.accentTextShadow,
						letterSpacing: -1,
					}}
				>
					{heading}
				</div>
				<div
					style={{
						width: dividerWidth,
						height: 1,
						background: `linear-gradient(90deg, transparent, ${colors.accent}, transparent)`,
						margin: "0 auto 20px auto",
					}}
				/>
				<div
					style={{
						fontSize: 32,
						color: colors.textMuted,
						fontFamily: fonts.heading,
						fontStyle: "italic",
						opacity: msgOpacity,
					}}
				>
					{message}
				</div>
			</div>

			{/* Bottom bar */}
			<div
				style={{
					position: "absolute",
					bottom: 60,
					left: "50%",
					transform: "translateX(-50%)",
				}}
			>
				<div
					style={{
						fontSize: 22,
						color: colors.textMuted,
						fontFamily: fonts.mono,
						opacity: 0.5,
						letterSpacing: 1,
					}}
				>
					{branding.channel}
				</div>
			</div>
		</AbsoluteFill>
	);
};
