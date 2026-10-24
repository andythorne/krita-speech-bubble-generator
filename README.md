# Krita Speech Bubble Generator

Create and edit speech, thought and shouting bubbles without leaving Krita.
Enter your dialogue, choose a style and position the tail in the preview.

![Examples of speech, thought and shouting bubbles](docs/images/bubble-preview.svg)

## Install

1. Download the plugin ZIP from the repository's [Releases page](../../releases).
   Use the plugin ZIP, not GitHub's **Source code** archive.
2. In Krita, choose **Tools > Scripts > Import Python Plugin...** and select
   the ZIP.
3. Restart Krita. If needed, enable **Krita Speech Bubble Generator** under
   **Settings > Configure Krita > Python Plugin Manager**, then restart again.
4. Open **Settings > Dockers > Krita Speech Bubble Generator**.

For manual installation, open **Settings > Manage Resources > Open Resource
Folder**. Copy `krita_speech_bubble_generator.desktop` and the
`krita_speech_bubble_generator/` folder from the ZIP into its `pykrita`
directory. Enable the plugin and restart Krita.

### Upgrading from the Rogudator-named version

Disable the old plugin first. To avoid duplicate dockers, remove its
`rogudators_speech_bubble_generator.desktop` file and
`rogudators_speech_bubble_generator/` folder from `pykrita`. Bubbles saved by
earlier versions of this fork remain editable without conversion.

## Create a bubble

1. Open a document and the plugin docker.
2. Enter dialogue in **Text**. Choose a style and appearance in **Bubble**.
3. In **Tail**, leave **Enabled** checked and set a length and direction, or
   drag the blue handle in the preview. Enable **Advanced** to position the
   start and end independently.
4. Choose **New vector layer** or **Selected vector layer**, then click
   **Add on Page**.
5. Move the bubble on the canvas with Krita's shape-selection tool. Click
   **New bubble** to start another.

The blue end handle and Advanced mode's green start handle are editing aids;
they will not appear in your artwork. The docker remembers your dialogue and
options between sessions. New bubbles keep the current options, while selecting
a saved bubble loads its own settings.

![The Krita docker showing a live bubble preview and editing controls](docs/images/example.png)

## Customize

- **Text:** Choose a font, size and colour. Select words to make them bold or
  italic, or use **Ctrl+B** and **Ctrl+I**. Choose **Standard** automatic wrapping
  or **Diamond** for short/long/short lines. Turn automatic wrapping off to use
  **Characters per line**. Enable optical vertical centering to balance the
  lettering visually. For Square shapes, choose **Text alignment (Square)**:
  **Left**, **Center** (the default) or **Right**, independently of wrapping.
  Other shapes keep centered text. Older saved bubbles default to Center.
- **Bubble:** Combine any **Shape** (Oval, Square or Tracing) with any **Style**
  (Sharp, Rounded, Thought or Shouting). Tracing follows the text layout;
  Thought rounds sharp corners beneath its cloud lobes so no rectangular corners
  protrude around the text; Shouting adds spikes. Adjust fill, outline,
  padding and the style's irregularity and node controls.
  **Advanced padding** offers separate horizontal and vertical padding, plus
  squareness for Oval. Turning it off resets vertical padding and squareness.
- **Tail:** Use **Enabled** to hide or restore the tail without losing its
  settings. Aim with the compass or drag the blue end handle. **Lock tail
  length** keeps the length fixed while aiming; **Curve** bends the tail.
  Enable **Advanced** to drag the green start along the bubble edge independently
  of the blue end. The compass and length controls apply only in simple mode.
  For Thought style, adjust **# of thought blobs** (1-10, default 3) and
  **Thought blob size**.
- **Copy Style:** Copy a bubble's appearance and text layout to other bubbles,
  including tail curvature and thought blob count and size. Dialogue, per-word
  emphasis and tail placement settings stay unchanged.

The **Text**, **Bubble** and **Tail** tabs group related controls. The preview
can show nearby canvas artwork while you edit; use **Refresh background** after
changing other artwork.

## Edit bubbles

Select a generated bubble on the canvas with Krita's shape-selection tool.
Changes in the docker update it automatically after a short pause. Use
**Update on Page** to apply the current settings immediately.

Save your document as `.kra` to keep bubbles editable. Keep each generated
bubble group intact; manually edited shapes inside it are rebuilt when the
bubble is updated. Copy and paste whole bubble groups between documents or vector
layers, or include them in a native vector-layer merge. Select the pasted group
to keep editing its dialogue, appearance and tail independently of the original.
Multiple bubbles can share a vector layer: select one group at a time to edit it;
other bubbles and artwork on that layer are left alone.

Newly created or edited bubbles carry their editing settings with the group.
Before copying an older bubble, select it in its original document with this
version of the plugin so its settings can travel too. If a tagged bubble does not
reconnect automatically, select its intact group and choose **Import > Recover
selected bubble**. Recovery works on shared layers, including bubbles with
identical or empty dialogue when their settings are available. Missing or
ambiguous older settings are refused rather than guessed; if an older paste has
lost its settings, select the original bubble and copy it again.

Older bubbles remain editable. Selecting one leaves the artwork unchanged;
its next edit may update its layout.

## Import an original Rogudator bubble

Select the old bubble's vector layer, open **Import**, then click
**Import old bubble**. The layer must contain one ungrouped bubble and its text;
layers with other artwork or multiple bubbles are not imported. If another
bubble is selected, click **New bubble** first.

Import keeps the original artwork's appearance until you edit it. **The first
edit redraws it with the current generator**, so its outline, text layout and
tail may change; per-word formatting such as bold is not preserved. Save a copy
first if you need to keep the original appearance. After importing, save as
`.kra` to edit the bubble normally in the future.

## Contributing

Bug reports, ideas and contributions are welcome. See
[CONTRIBUTING.md](CONTRIBUTING.md).

## Credits and license

Based on [Rogudator's Speech Bubble Generator](https://github.com/rogudator/rogudators_speech_bubble_generator)
by **Danil Zotin (rogudator)**, with additional styles, interactive previews
and saved-bubble editing developed in this fork. This is an independent
project, not an official Krita plugin.

Licensed under the [GNU General Public License v3](LICENSE).
