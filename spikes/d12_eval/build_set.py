"""D12 draft evaluation set: 40 product types x 5 listings = 200. Labels set by Claude from HTS/WCO headings; need human spot-check."""
import json, itertools
T = [
# ceramics
("6912.00","stoneware mug",["Handmade stoneware coffee mug","Speckled glaze ceramic mug 350ml","Stoneware tea mug with handle"],["Wheel-thrown stoneware, glazed, dishwasher safe","Hand glazed stoneware mug, microwave safe"]),
("6912.00","earthenware bowl",["Rustic earthenware serving bowl","Hand painted ceramic cereal bowl","Earthenware soup bowl set of 2"],["Glazed earthenware, kitchen use","Terracotta-bodied glazed bowl for the table"]),
("6912.00","stoneware plate",["Stoneware dinner plate 27cm","Matte glaze ceramic side plate","Handmade stoneware dessert plate"],["Stoneware, food safe glaze","Thrown on the wheel, kiln fired stoneware"]),
("6911.10","porcelain plate",["White porcelain dinner plate","Fine porcelain salad plate set of 4","Porcelain dining plate gold rim"],["Fine white porcelain, dishwasher safe","Vitrified porcelain tableware"]),
("6911.10","porcelain teacup",["Bone china teacup and saucer","Porcelain tea cup with saucer","Fine porcelain espresso cup set"],["Translucent porcelain with gilt rim","Porcelain cup for tea or coffee"]),
("6913.90","ceramic vase",["Hand painted ceramic vase","Earthenware flower vase 25cm","Decorative stoneware bud vase"],["Decorative vase for display, earthenware","Ornamental ceramic vase, glazed"]),
("6913.90","ceramic figurine",["Ceramic owl figurine","Hand glazed stoneware animal ornament","Decorative earthenware bird statuette"],["Decorative ornament, not for food use","Hand-made glazed ceramic figure for shelf display"]),
("6914.90","ceramic planter",["Glazed ceramic plant pot with saucer","Terracotta planter 15cm","Stoneware indoor plant pot"],["Ceramic flower pot for houseplants","Drainage hole, glazed ceramic planter"]),
("6907.21","ceramic tile",["Glazed ceramic wall tile 10x10","Handmade ceramic backsplash tiles pack of 20","Ceramic floor tile 30x30 matt"],["Ceramic tile, low water absorption","Kiln fired tile for kitchen walls"]),
("6912.00","ceramic coaster",["Ceramic coaster set of 4","Hand painted stoneware drinks coasters","Glazed ceramic cup coaster"],["Cork backed ceramic coasters","Stoneware coaster for tables"]),
# leather
("4202.31","leather wallet",["Leather bifold wallet men's","Full grain leather wallet with card slots","Slim leather trifold wallet"],["Genuine leather, RFID lining","Handstitched cowhide wallet"]),
("4202.31","leather card holder",["Leather card holder slim","Vegetable tanned leather card case","Minimalist leather card wallet"],["Holds 6 cards, full grain leather","Pocket card case in calf leather"]),
("4202.21","leather handbag",["Leather tote handbag","Genuine leather shoulder bag, tan","Women's leather satchel handbag"],["Full grain leather with zip closure","Cowhide handbag with inner pockets"]),
("4202.11","leather suitcase",["Leather weekend suitcase","Cabin size leather trolley case","Vintage style leather travel trunk"],["Leather exterior, lined interior with lock","Suitcase with leather outer surface"]),
("4203.30","leather belt",["Leather belt brown 35mm","Men's full grain leather belt","Handmade leather belt brass buckle"],["Vegetable tanned cowhide belt","Genuine leather belt, adjustable"]),
("4203.29","leather gloves",["Leather driving gloves","Lambskin gloves ladies","Men's winter leather gloves"],["Soft leather with fleece lining","Goat leather gloves, touch screen tips"]),
("4203.10","leather jacket",["Leather biker jacket","Genuine cowhide bomber jacket","Women's lambskin leather jacket"],["Real leather outerwear, zip front","Full leather jacket, quilted lining"]),
("4201.00","leather dog collar",["Leather dog collar and lead set","Handstitched leather dog collar","Padded leather dog lead"],["Leather pet collar, brass fittings","Dog harness and leash in leather"]),
("4202.31","leather coin purse",["Leather coin purse","Small zip purse in goat leather","Leather change pouch"],["Pocket sized leather purse","Genuine leather coin wallet"]),
("4202.21","leather crossbody bag",["Leather crossbody bag","Small leather handbag with strap, black","Leather saddle bag crossbody"],["Adjustable strap, genuine leather","Compact bag with leather outer surface"]),
# cotton
("6109.10","cotton t-shirt",["Organic cotton t-shirt","Men's crew neck tee 100% cotton","Women's cotton jersey t-shirt"],["Knitted cotton jersey, short sleeve","Soft cotton tee, unisex"]),
("6110.20","cotton hoodie",["Cotton hoodie pullover","Knitted cotton fleece hoodie","Unisex cotton zip hoodie"],["Cotton fleece knit, kangaroo pocket","Heavy cotton knit sweatshirt with hood"]),
("6110.20","cotton sweater",["Cotton knit sweater","Chunky cotton jumper","Women's cotton cardigan sweater"],["100% cotton knit pullover","Knitted cotton jersey jumper"]),
("6115.95","cotton socks",["Cotton ankle socks 5 pack","Men's cotton crew socks","Women's cotton sports socks"],["Knitted socks 98% cotton","Cotton rich hosiery, pack"]),
("6104.62","cotton leggings",["Women's cotton leggings","Stretch cotton leggings black","Cotton yoga leggings"],["Knitted cotton elastane leggings","Cotton blend tights, 95% cotton"]),
("6111.20","cotton baby bodysuit",["Cotton baby bodysuit","Organic cotton baby romper","Infant cotton onesie pack of 3"],["Knitted cotton garment for babies","Soft cotton baby clothing"]),
("6203.42","cotton jeans",["Cotton denim jeans men's","Straight fit jeans 100% cotton","Men's selvedge denim jeans"],["Woven cotton denim trousers","Five pocket jeans, cotton"]),
("6203.42","cotton chinos",["Men's cotton chinos","Slim fit cotton chino trousers","Cotton twill trousers men's"],["Woven cotton twill, flat front","Men's cotton trousers"]),
("6204.42","cotton dress",["Women's cotton summer dress","Woven cotton sundress midi","Cotton shirt dress ladies"],["100% woven cotton, knee length","Lightweight cotton dress"]),
("6205.20","cotton shirt",["Men's cotton oxford shirt","Woven cotton button down shirt","Men's cotton check shirt"],["100% cotton woven shirt, long sleeve","Cotton poplin dress shirt men's"]),
("6206.30","cotton blouse",["Women's cotton blouse","Embroidered cotton blouse","Woven cotton peasant blouse"],["Cotton voile blouse, ladies","100% cotton woven blouse"]),
("6302.31","cotton sheet set",["Cotton bed sheet set queen","Percale cotton sheets white","Cotton flat sheet and fitted sheet"],["Plain white 100% cotton bed linen","Woven cotton percale 300 thread count"]),
("6302.31","cotton pillowcase",["Cotton pillowcase pair","Percale cotton pillow cover","Plain cotton pillowcase set of 2"],["Plain dyed cotton bed linen","100% cotton pillow cases"]),
("6302.21","printed cotton duvet",["Printed cotton duvet cover","Floral cotton bed linen double","Block print cotton quilt cover"],["Printed 100% cotton bed linen","Cotton duvet cover with printed pattern"]),
("6302.60","cotton towel",["Terry cotton bath towel","Heavy 600gsm cotton towel","Cotton hand towel set terry"],["Terry towelling, 100% cotton","Absorbent cotton terry bath linen"]),
("6302.51","cotton tablecloth",["Block print cotton tablecloth","Cotton table cover 150x250","Linen look cotton tablecloth"],["Cotton table linen, hand block printed","Woven cotton tablecloth"]),
("6302.51","cotton napkins",["Cotton napkins set of 6","Woven cotton dinner napkins","Cloth napkins cotton"],["Table napkins 100% cotton","Plain woven cotton napkins"]),
("6302.91","cotton tea towel",["Cotton tea towel","Printed cotton kitchen towel","Woven cotton dish towel set"],["Non-terry cotton kitchen linen","Plain weave cotton tea towels"]),
("6303.91","cotton curtains",["Cotton curtains pair","Woven cotton curtain panels","Cotton eyelet curtains"],["100% woven cotton curtains, lined","Window curtains in cotton canvas"]),
("6203.42","cotton cargo pants",["Men's cotton cargo pants","Cotton cargo trousers","Woven cotton work trousers"],["Woven cotton drill, side pockets","Cotton trousers with cargo pockets"]),
]
rows=[]
for hs,kind,titles,descs in T:
    combos=list(itertools.product(titles,descs))[:5]
    for i,(t,d) in enumerate(combos):
        rows.append({"id":f"{len(rows)+1:03d}","type":kind,"title":t,"description":d,"hs6":hs,
          "source":f"HTS {hs} subheading text (USITC) and Chapter {hs[:2]} notes","label_status":"draft, Claude-labelled"})
# pad to 200 with the 5th combination variant if short
json.dump(rows,open("listings.json","w"),indent=1)
print(len(rows),"listings,",len(T),"types")
