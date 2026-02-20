import rasterio
from rasterio.io import DatasetReader
from rasterio.mask import mask
from shapely.geometry import Polygon
from typing import List, Optional
import numpy as np
from PIL import Image, ImageOps

def generate_layer_texture(
    src: DatasetReader,
    layer_polys: List[Polygon],
    output_path: Optional[str] = None,
    normalize_contrast: bool = True,
    normalize_cutoff: float = 1.0,
    normalize_bounds: Optional[tuple[float, float]] = None,
    gamma: float = 1.0,
) -> Image.Image:
    """
    Generate a masked, dithered texture for a specific elevation layer.
    
    Args:
        src: Open rasterio dataset of the imagery (RGB).
        layer_polys: List of polygons for this layer/slice.
        output_path: If provided, save PNG here.
        
    Returns:
        PIL Image object (1-bit dithered).
    """
    
    # Masking
    # crop=False ensures we keep the full extent of the src dataset (alignment!)
    # invert=False means we keep what is INSIDE the shapes.
    out_image, out_transform = mask(src, layer_polys, crop=False, filled=True)
    
    # out_image is (Bands, Height, Width).
    # Assuming RGB (3 bands) or RGBA (4 bands).
    
    # Convert to HWC for generic image processing
    data = out_image.transpose(1, 2, 0)
    
    # If nodata is involved (filled=True fills with nodata, usually 0 or 255 depending on dtype)
    # We want "No Data" to be White (No Burn).
    
    # Check src nodata
    nodata = src.nodata
    if nodata is None:
        nodata = 0 # Assume 0 is nodata if not set
        
    # Create mask of valid data (where any band is not nodata? or based on mask return?)
    # rasterio mask fills outside with nodata.
    
    # Build grayscale in float space so normalization is consistent across layers.
    if data.shape[2] >= 3:
        rgb = data[:, :, :3].astype(np.float32)
        gray = rgb[:, :, 0] * 0.2989 + rgb[:, :, 1] * 0.5870 + rgb[:, :, 2] * 0.1140
        valid_mask = np.ones(gray.shape, dtype=bool)
        if nodata is not None:
            try:
                valid_mask = np.any(data[:, :, :3] != nodata, axis=2)
            except Exception:
                valid_mask = np.ones(gray.shape, dtype=bool)
    else:
        gray = data[:, :, 0].astype(np.float32)
        valid_mask = np.ones(gray.shape, dtype=bool)
        if nodata is not None:
            valid_mask = data[:, :, 0] != nodata

    if normalize_bounds is not None:
        low, high = normalize_bounds
        if high > low:
            gray = (gray - low) / (high - low)
            gray = np.clip(gray, 0, 1) * 255.0
    elif normalize_contrast:
        gray_img = Image.fromarray(np.clip(gray, 0, 255).astype('uint8'), 'L')
        gray_img = ImageOps.autocontrast(gray_img, cutoff=normalize_cutoff)
        gray = np.asarray(gray_img, dtype=np.float32)

    # Set nodata to white so it doesn't burn.
    gray = np.where(valid_mask, gray, 255.0)

    # Gamma correction to expand contrast for engraving materials.
    if gamma and gamma > 0 and abs(gamma - 1.0) > 1e-3:
        gray = np.clip(gray / 255.0, 0, 1) ** gamma * 255.0

    # Convert to Grayscale PIL
    gray = Image.fromarray(np.clip(gray, 0, 255).astype('uint8'), 'L')
    
    # Improve Contrast? Terrain can be flat gray.
    # Optional: Equilize transform?
    # stick to simple for now.
    
    # Dither (Floyd-Steinberg)
    dithered = gray.convert('1', dither=Image.Dither.FLOYDSTEINBERG)
    
    if output_path:
        dithered.save(output_path)
        
    return dithered
