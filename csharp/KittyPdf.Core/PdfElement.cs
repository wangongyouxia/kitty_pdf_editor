namespace KittyPdf.Core;

public enum PdfElementKind
{
    Unknown = 0,
    Text = 1,
    Path = 2,
    Image = 3,
    Shading = 4,
    Form = 5,
}

/// <summary>
/// A snapshot of one page object as the editor sees it.  Geometry is in
/// PDF points with the PDF origin (bottom-left, y-up).  <see cref="Index"/>
/// is the object's position in the page's object list — the stable handle
/// the editor uses to re-find the live native object when committing an
/// edit (we never cache raw pointers across a content regeneration).
/// </summary>
public sealed class PdfElement
{
    public required int PageIndex { get; init; }
    public required int Index { get; init; }
    public required PdfElementKind Kind { get; init; }

    // PDF-space bounds (y-up).
    public double Left { get; init; }
    public double Bottom { get; init; }
    public double Right { get; init; }
    public double Top { get; init; }

    public double Width => Right - Left;
    public double Height => Top - Bottom;

    // Text-only attributes (null / 0 for non-text objects).
    public string? Text { get; init; }
    public string? FontName { get; init; }
    public float FontSize { get; init; }

    /// <summary>PDF font weight: 400 = normal, 700 = bold. 0 if unknown.</summary>
    public int FontWeight { get; init; }

    /// <summary>True when the font weight or descriptor flags mark it bold.</summary>
    public bool IsBold { get; init; }

    /// <summary>True when the font has a non-zero italic angle or the italic flag.</summary>
    public bool IsItalic { get; init; }

    /// <summary>Fill colour 0..1 RGBA.</summary>
    public (double R, double G, double B, double A) Color { get; init; } = (0, 0, 0, 1);

    public override string ToString()
    {
        if (Kind == PdfElementKind.Text)
            return $"#{Index} TEXT \"{Text}\" font={FontName} w={FontWeight} " +
                   $"bold={IsBold} italic={IsItalic} size={FontSize:0.#} " +
                   $"@({Left:0.#},{Bottom:0.#})-({Right:0.#},{Top:0.#})";
        return $"#{Index} {Kind} @({Left:0.#},{Bottom:0.#})-({Right:0.#},{Top:0.#})";
    }
}
