# Krita Speech Bubble Generator

Create speech, thought and shouting bubbles without leaving Krita. Type your
dialogue, choose a style, and drag the tail into place.

![Examples of speech, thought and shouting bubbles](docs/images/bubble-preview.svg)

## Features

| Feature | What you can do |
| --- | --- |
| Five bubble styles | Choose Oval, Rounded, Square, Thought or Shouting. |
| Shouting shapes | Choose Balanced curves, Angular straight-sided spikes, Punchy's shorter, broader spikes, or Expressive curves with varied spacing and gentle lean. |
| Adjustable nodes | Set 8-64 nodes for more or fewer shouting spikes or thought-cloud lobes. Each bubble keeps its node counts. |
| Drag-to-position tails | Aim the tail in the preview, with an optional length lock to keep it consistent. |
| Expressive shapes | Adjust thought-cloud irregularity, thought-trail blob size, and shouting-spike spacing with subtle height and valley-depth variation. Your pattern stays stable while you edit. |
| Text and appearance | Choose fonts, text size, fill and outline colours. Use automatic wrapping or control line breaks yourself. Drag the grip below the text input to resize it. |
| Bubble padding | Adjust the space between text and the bubble edge for every style. Padding scales with your text size and is saved with each bubble. |
| Live editing | Select a saved bubble to edit its text and appearance directly from the docker. Changes appear on the canvas after a short pause. |
| Canvas-aware preview | See the surrounding artwork while editing, so you can point the tail at the right character. |
| Flexible layers | Create a new vector layer or keep several independently editable bubbles on one layer. |
| Editable later | Save as `.kra` and return to your bubbles later, keeping their canvas position, rotation and scale when updating. |

## Installation

1. Download the plugin ZIP attached to a release on this repository's
   [Releases page](../../releases). Use the plugin ZIP, not GitHub's **Source code**
   archives.
2. In Krita, choose **Tools > Scripts > Import Python Plugin...** and select the ZIP.
3. Restart Krita. If needed, enable **Krita Speech Bubble Generator** under
   **Settings > Configure Krita > Python Plugin Manager**, then restart again.
4. Open **Settings > Dockers > Krita Speech Bubble Generator**.

For manual installation, open **Settings > Manage Resources > Open Resource
Folder**. Copy `krita_speech_bubble_generator.desktop` and the
`krita_speech_bubble_generator/` folder from the ZIP into its `pykrita` directory,
then enable the plugin and restart Krita.

### Upgrading from the Rogudator-named version

Disable the old plugin before installing this one. To avoid duplicate dockers,
remove its `rogudators_speech_bubble_generator.desktop` file and
`rogudators_speech_bubble_generator/` folder from `pykrita`.

Bubbles saved by earlier versions of this fork remain editable; no document
conversion is needed. Bubbles from the original upstream plugin without saved
editing settings cannot be reopened in the generator.

## Make your first bubble

1. Open a document and the **Krita Speech Bubble Generator** docker.
2. Enter your dialogue below the preview, then choose a font and bubble style.
   Adjust **Padding** to control the space around the text: 100% is one text-size
   unit on each side, and 0% removes the extra space. Curved and irregular
   outlines still leave room to enclose the text.
3. Set a tail length above zero and drag the blue preview handle to aim it.
   Leave **Lock tail length** on to change direction only, or turn it off to
   adjust both direction and length by dragging.
4. Choose **New vector layer** or **Selected vector layer**, then click
   **Add on Page**.
5. Move the bubble on the canvas with Krita's shape-selection tool. Click
   **New bubble** in the docker when you are ready to create another one.

The blue handle is only an editing aid; it does not appear in your artwork.
For a bubble without a tail, enable **Lock tail length** above the length slider
and move the slider to zero.
With **Lock tail length** off, the blue handle stays visible even at zero length.
Drag it outward to create a tail, or into the bubble to reduce the length to zero.
Resizing the text input keeps the preview height and the controls above it
unchanged.

For **Shouting** bubbles, choose a **Shape** in the Shouting controls, then adjust
**Irregularity**. All four shapes keep spike heights and valley depths restrained,
even at high irregularity. The shape is saved with each bubble; switching shapes
does not reset its random seed.

Use **Nodes** in the Shouting or Thought controls to change the number of spikes
or cloud lobes. Higher counts give a denser outline; lower counts give fewer,
broader features. Shouting and Thought keep separate counts, and changing the
count leaves text layout, padding and the locked tail length unchanged.

## Edit an existing bubble

Select a generated bubble on the canvas using
Krita's shape-selection tool. Its text and settings load into the docker, and
your changes always update the bubble automatically after a short pause.
The main button becomes
**Update on Page**, so it updates the selected bubble rather than adding another.
There is no separate manual-editing mode or live-update switch.

**Canvas background** shows the nearby artwork in the preview while editing.
It follows the bubble when you move, rotate or scale it on the canvas. Use
**Refresh background** after changing other artwork.

Save your document in **Krita's `.kra` format** to keep bubble editing settings.
Keep the generated bubble group intact: updating rebuilds its contents, so
manual edits to individual vector shapes inside the group are not retained.

## Contributing

Bug reports, ideas and contributions are welcome. See
[CONTRIBUTING.md](CONTRIBUTING.md) for reporting issues and working on the plugin.

## Credits and license

Based on [Rogudator's Speech Bubble Generator](https://github.com/rogudator/rogudators_speech_bubble_generator)
by **Danil Zotin (rogudator)**, with additional styles, interactive previews and
saved-bubble editing developed in this fork. This is an independent project,
not an official Krita plugin.

Licensed under the [GNU General Public License v3](LICENSE).
