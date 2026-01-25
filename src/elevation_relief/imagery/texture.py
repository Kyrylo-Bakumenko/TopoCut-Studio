import rasterio
from rasterio.io import DatasetReader
from rasterio.mask import mask
from shapely.geometry import Polygon
from typing import List, Optional
import numpy as np
from PIL import Image

def generate_layer_texture(
    src: DatasetReader,
    layer_polys: List[Polygon],
    output_path: Optional[str] = None
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
    
    # Let's convert to PIL
    if data.shape[2] >= 3:
        img = Image.fromarray(data[:, :, :3].astype('uint8'), 'RGB')
    else:
        # Grayscale
        img = Image.fromarray(data[:, :, 0].astype('uint8'), 'L').convert('RGB')
        
    # Handle transparency/nodata -> White
    # If we have an identified nodata value in the array
    # Create an alpha mask where data == nodata
    try:
        alpha = np.all(data[:, :, :src.count] != nodata, axis=2).astype(np.uint8) * 255
        alpha_img = Image.fromarray(alpha, 'L')
        img.putalpha(alpha_img)
    except:
        pass

    # Composite onto White background
    background = Image.new("RGB", img.size, (255, 255, 255))
    background.paste(img, mask=img.split()[3] if len(img.split()) > 3 else None)
    
    # Convert to Grayscale
    gray = background.convert('L')
    
    # Improve Contrast? Terrain can be flat gray.
    # Optional: Equilize transform?
    # stick to simple for now.
    
    # Dither (Floyd-Steinberg)
    dithered = gray.convert('1', dither=Image.Dither.FLOYDSTEINBERG)
    
    if output_path:
        dithered.save(output_path)
        
    return dithered
