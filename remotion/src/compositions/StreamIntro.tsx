import {
	AbsoluteFill,
	interpolate,
	spring,
	useCurrentFrame,
	useVideoConfig,
} from "remotion";
import { type Brand, type ThemeFonts, getTheme, layout } from "../lib/theme";

type Props = {
	brand?: Brand;
	episodeTitle: string;
};

/** Animated code lines that type in from the left. */
const CodeLine: React.FC<{
	text: string;
	delay: number;
	y: number;
	color: string;
	fonts: ThemeFonts;
	maxOpacity?: number;
}> = ({ text, delay, y, color, fonts, maxOpacity = 0.3 }) => {
	const frame = useCurrentFrame();
	const chars = Math.floor(
		interpolate(frame - delay, [0, 30], [0, text.length], {
			extrapolateLeft: "clamp",
			extrapolateRight: "clamp",
		}),
	);
	const opacity = interpolate(frame - delay, [0, 5], [0, maxOpacity], {
		extrapolateLeft: "clamp",
		extrapolateRight: "clamp",
	});

	return (
		<div
			style={{
				position: "absolute",
				top: y,
				left: layout.padding,
				fontFamily: fonts.mono,
				fontSize: 22,
				color,
				opacity,
				whiteSpace: "pre",
				letterSpacing: 0.5,
			}}
		>
			{text.slice(0, chars)}
			{chars < text.length && (
				<span style={{ opacity: frame % 16 < 8 ? 1 : 0 }}>▌</span>
			)}
		</div>
	);
};

const codeLinesForBrand: Record<Brand, string[]> = {
	turtlewolfe: [
		'import { stream } from "@turtlewolfe/live";',
		"const episode = await stream.start({",
		'  host: "TurtleWolfe",',
		'  cohost: "MoltBot",',
		"  viewers: Infinity,",
		"});",
		"await episode.begin();",
	],
	scripthammer: [
		'import { forge } from "@scripthammer/core";',
		'const app = forge.create({ name: "SaaS" });',
		'app.addFeature("auth", { provider: "supabase" });',
		'app.addFeature("payments", { stripe: true });',
		'app.addFeature("ai", { terminals: 27 });',
		"const deploy = await app.build();",
		"await deploy.ship();",
	],
};

export const StreamIntro: React.FC<Props> = ({
	brand = "turtlewolfe",
	episodeTitle,
}) => {
	const frame = useCurrentFrame();
	const { fps } = useVideoConfig();
	const { colors, fonts, effects, branding } = getTheme(brand);
	const codeLines = codeLinesForBrand[brand];
	const codeOpacity = brand === "scripthammer" ? 0.7 : 0.3;
	const codeColor = brand === "scripthammer" ? colors.accent : colors.codeGreen;

	// Brand name animation
	const brandScale = spring({
		frame: frame - 60,
		fps,
		config: { damping: 10, mass: 0.8 },
	});
	const brandOpacity = interpolate(frame, [60, 80], [0, 1], {
		extrapolateRight: "clamp",
		extrapolateLeft: "clamp",
	});

	// Divider line animation
	const dividerWidth = interpolate(frame, [90, 130], [0, 400], {
		extrapolateLeft: "clamp",
		extrapolateRight: "clamp",
	});

	// Episode title fades in after brand
	const titleOpacity = interpolate(frame, [120, 150], [0, 1], {
		extrapolateRight: "clamp",
		extrapolateLeft: "clamp",
	});
	const titleY = spring({
		frame: frame - 120,
		fps,
		config: { damping: 14 },
	});

	// Fade out everything at the end
	const fadeOut = interpolate(frame, [260, 290], [1, 0], {
		extrapolateLeft: "clamp",
		extrapolateRight: "clamp",
	});

	return (
		<AbsoluteFill
			style={{ background: effects.bgGradient, opacity: fadeOut }}
		>
			{/* Background code lines */}
			{codeLines.map((line, i) => (
				<CodeLine
					key={`code-${i}`}
					text={line}
					delay={i * 8}
					y={120 + i * 36}
					color={codeColor}
					fonts={fonts}
					maxOpacity={codeOpacity}
				/>
			))}

			{/* Center brand */}
			<div
				style={{
					position: "absolute",
					top: "50%",
					left: "50%",
					transform: `translate(-50%, -50%) scale(${interpolate(brandScale, [0, 1], [0.8, 1])})`,
					opacity: brandOpacity,
					textAlign: "center",
				}}
			>
				{/* Brand name — bold monospace for technical impact */}
				<div
					style={{
						fontSize: 96,
						fontWeight: 900,
						fontFamily: fonts.display,
						color: colors.accent,
						letterSpacing: 4,
						textTransform: "uppercase",
						textShadow: effects.accentTextShadow,
					}}
				>
					{branding.name}
				</div>

				{/* Thin divider */}
				<div
					style={{
						width: dividerWidth,
						height: 1,
						background: `linear-gradient(90deg, transparent, ${colors.accent}, transparent)`,
						margin: "16px auto",
					}}
				/>

				{/* Tagline — serif italic for editorial contrast */}
				<div
					style={{
						fontSize: 28,
						color: colors.textMuted,
						fontFamily: fonts.heading,
						fontStyle: "italic",
						marginTop: 4,
						letterSpacing: 1,
					}}
				>
					{branding.tagline}
				</div>
			</div>

			{/* Episode title */}
			<div
				style={{
					position: "absolute",
					bottom: 160,
					left: "50%",
					transform: `translateX(-50%) translateY(${interpolate(titleY, [0, 1], [20, 0])}px)`,
					opacity: titleOpacity,
					fontSize: 48,
					fontWeight: 600,
					color: colors.text,
					fontFamily: fonts.heading,
					textAlign: "center",
					letterSpacing: 0.5,
				}}
			>
				{episodeTitle}
			</div>
		</AbsoluteFill>
	);
};
