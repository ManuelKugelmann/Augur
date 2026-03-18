# Image Prompt Guide for Augur News Agents

When calling `generate_article_image()`, write a **scene description** — not
a headline or abstract concept. The brand's style prefix is auto-prepended,
so focus only on the scene.

## Rules

1. **Describe a real scene, not a concept.** "A flooded street in Bangkok with
   rescue boats" — not "Climate change impact on Southeast Asia."
2. **Be specific.** Name objects, locations, lighting, weather. Vague prompts
   produce generic stock photos.
3. **One subject, one moment.** Don't cram multiple events into one image.
4. **No text, logos, or UI elements.** FLUX cannot render readable text.
5. **No named real people.** Describe roles instead: "a trader", "emergency
   workers", "a central banker at a podium."
6. **Keep it under 200 words.** Longer prompts dilute focus.
7. **Match the article tone.** Tomorrow = urgent/current. Leap = speculative/
   cinematic.

## Structure

```
[Setting/location], [subject doing action], [lighting/weather/time],
[key details], [mood/atmosphere]
```

## Examples

### General (The Augur / Der Augur)

**Good**: "A dried-out reservoir in southern Spain, cracked earth stretching
to a distant dam with visibly low water levels, harsh midday sun, scattered
dead vegetation, a single farmer inspecting the dry lakebed."

**Bad**: "Water crisis in Europe" (too abstract)

### Financial (Financial Augur / Finanz Augur)

**Good**: "Trading floor viewed from above, multiple screens showing red
downward charts, traders in shirtsleeves gesturing urgently, blue-tinted
overhead lighting, papers scattered on desks, early morning atmosphere."

**Bad**: "Stock market crash" (too abstract)

### Horizon-specific tone

- **Tomorrow**: Immediate, news-wire feel. Current events, real places.
- **Soon**: Near-term tension. Situations building toward a tipping point.
- **Future**: Wider lens. Infrastructure, systems, large-scale change.
- **Leap**: Cinematic, speculative. 2050s cityscapes, transformed landscapes.
